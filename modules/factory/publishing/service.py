"""Publication service (F31): manual registration + authorised
automated posting, modelled separately from generation and delivery.

- Intent is persisted BEFORE any transport call; the durable record
  carries a stable idempotency key, so a lost acknowledgement never
  becomes a second public post — reconcile by provider identity.
- Provider-confirmed states only: `public` requires the platform's own
  post id/url/published_at. An accepted request or a draft is not a
  public post.
- Cadence is enforced per (platform, account) per configured timezone
  day BEFORE submission.
- Metadata edits and deletion are separate explicit actions; nothing
  here silently removes a post.
"""
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..domain.errors import ContractError
from ..domain.records import Publication
from ..integrations.publisher import (ACCEPTED, TERMINAL,
                                      PublishTransportError)

PUBLISHABLE = {"youtube"}            # qualified automated routes
MANUAL_PLATFORMS = {"youtube", "tiktok", "instagram"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _key(publication_id, final_sha256, platform, account_id):
    return hashlib.sha256(
        f"{publication_id}|{final_sha256}|{platform}|{account_id}"
        .encode()).hexdigest()[:32]


class PublishingService:
    def __init__(self, db, publisher=None, accounts=None,
                 max_per_day=2, effects=None, executor=None):
        """accounts: {"platform:account_id": provider_user} — the known
        valid destinations. Unknown accounts are refused for both
        lanes."""
        from ..execution import Executor
        self.db = db
        self.effects = effects
        self.executor = executor or Executor(db)
        self.publisher = publisher
        self.accounts = dict(accounts or {})
        self.max_per_day = max_per_day

    # ------------------------------------------------------ intent --

    def plan(self, publication_id, *, variant_plan_id, final_sha256,
             platform, account_id, metadata=None, visibility="public",
             scheduled_at="", tz="UTC", media_url="",
             horizon_policy=None, authorization_id="", now="",
             automated=True):
        """Persist the publication intent — no transport call yet."""
        now = now or _now()
        if automated and platform not in PUBLISHABLE:
            raise ContractError("unqualified_platform", "platform",
                                platform)
        self._account(platform, account_id)
        ZoneInfo(tz)                  # validate timezone name early
        p = Publication(schema_version="publication.v1",
                        id=publication_id, created_at=now,
                        variant_plan_id=variant_plan_id,
                        final_sha256=final_sha256, platform=platform,
                        account_id=account_id, status="requested",
                        visibility=visibility, scheduled_at=scheduled_at,
                        authorization_id=authorization_id,
                        idempotency_key=_key(publication_id,
                                             final_sha256, platform,
                                             account_id),
                        metadata=dict(metadata or {}),
                        media_url=media_url, timezone=tz,
                        horizon_policy=dict(horizon_policy or {}),
                        manual=not automated)
        p.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(p)
            u.events.append(f"publication:{publication_id}",
                            "publication_planned",
                            {"platform": platform,
                             "account_id": account_id})
        return p

    def authorize(self, publication_id, authorization_id, now=""):
        """Bind an Authorization record that has
        publication_authorized=True. Checked again at publish time."""
        row = self.db.uow().records.get("authorization",
                                       authorization_id)
        if row is None:
            raise ContractError("unknown_authorization",
                                "authorization_id", authorization_id)
        auth = json.loads(row["body"])
        if auth.get("status") != "authorized" or \
                not auth.get("publication_authorized"):
            raise ContractError("publication_not_authorized",
                                "authorization_id", authorization_id)
        self._set(publication_id, authorization_id=authorization_id)
        return {"authorization_id": authorization_id}

    # ----------------------------------------------------- publish --

    def publish(self, publication_id, *, video_path="", now=""):
        """Submit the persisted intent. Cadence and authorization are
        enforced before the transport call; a lost ack leaves the
        record `unknown` for reconciliation — never a blind repost."""
        now = now or _now()
        p = self._get(publication_id)
        if p is None:
            raise ContractError("unknown_publication", "id",
                                publication_id)
        if self.publisher is None:
            raise ContractError("no_publisher", "platform",
                                p["platform"])
        self._check_authorization(p, now)
        if p["status"] in ("public", "draft", "scheduled"):
            return {"status": p["status"], "request_id": p.get("request_id", "")}
        if p.get("attempt_id"):
            return self.reconcile(publication_id, now=now)
        if self.effects is None:
            raise ContractError("authority_required", "publication")
        request = {"publication_id": publication_id, "final_sha256": p["final_sha256"],
                   "platform": p["platform"], "account_id": p["account_id"],
                   "metadata": p.get("metadata") or {}, "visibility": p.get("visibility"),
                   "scheduled_at": p.get("scheduled_at"), "action": "publish"}
        with self.db.uow():
            self._check_cadence(p, now)
            aid = self.effects(request, f"publish:{publication_id}", "publication", "upload_post", "upload")
            self.executor.require_request(aid, request)
            self._set(publication_id, attempt_id=aid, status="uploading", dispatch_started_at=now)
        meta = p.get("metadata") or {}
        def upload():
            resp = self.publisher.upload(
                video_path=video_path, video_url=p.get("media_url", ""),
                title=meta.get("title", ""),
                description=meta.get("description", ""),
                platforms=(p["platform"],),
                visibility=p.get("visibility", "public"),
                schedule_date=p.get("scheduled_at", ""),
                user=self.accounts.get(
                    f"{p['platform']}:{p['account_id']}", ""),
                idempotency_key=p["idempotency_key"],
                extra_fields={"hashtags": ",".join(
                    meta.get("hashtags", []))})
            return dict(resp, operation_id=resp["request_id"])
        try:
            resp = self.executor.submit(aid, upload)
        except PublishTransportError as e:
            if e.status_code in (400, 401, 403, 409):
                self._set(publication_id, status="failed",
                          last_error=f"{e.status_code}:{e}")
                raise
            # ambiguous — the remote effect may exist
            self._set(publication_id, status="unknown",
                      last_error=str(e))
            return self.reconcile(publication_id, now=now)
        return self._apply(publication_id, resp, now)

    def _apply(self, publication_id, resp, now):
        status = resp.get("status", "accepted")
        fields = {"request_id": resp.get("request_id", "")}
        if status in ACCEPTED:
            fields["status"] = ("processing" if status == "processing"
                                else "uploading")
        elif status == "public":
            fields.update(status="public",
                          remote_post_id=resp.get("remote_post_id", ""),
                          post_url=resp.get("post_url", ""),
                          published_at=resp.get("published_at", now),
                          visibility=resp.get(
                              "visibility", "public"))
        elif status in TERMINAL:
            fields["status"] = status
            if status == "scheduled":
                fields["scheduled_at"] = resp.get(
                    "scheduled_at", fields.get("scheduled_at", ""))
        self._set(publication_id, **fields)
        self._event(publication_id, "publication_submitted",
                    {"request_id": fields.get("request_id", ""),
                     "status": fields.get("status", status)})
        return {"status": fields.get("status", status),
                "request_id": fields.get("request_id", "")}

    # --------------------------------------------------- reconcile --

    def reconcile(self, publication_id, now=""):
        """Ask the provider what actually happened — by request id, or
        by idempotency key when the ack never arrived. Only a
        provider-confirmed public state stamps published_at."""
        now = now or _now()
        p = self._get(publication_id)
        if p["status"] == "requested" and not p.get("attempt_id") and not p.get("request_id"):
            return {"status": "requested", "action": "safe_to_resubmit"}
        try:
            if p.get("request_id"):
                resp = self.publisher.status(p["request_id"])
            else:
                found = self.publisher.find_by_idempotency_key(
                    p["idempotency_key"])
                if found is None:
                    self._set(publication_id, status="unknown", last_error="no_remote_trace")
                    return {"status": "unknown", "action": "reconcile_or_review_evidence"}
                resp = found
        except PublishTransportError:
            self._set(publication_id, status="unknown")
            return {"status": "unknown",
                    "action": "retry_reconcile_later"}
        remote = resp.get("status", "unknown")
        if remote == "public":
            self._set(publication_id, status="public",
                      request_id=resp.get("request_id",
                                          p.get("request_id", "")),
                      remote_post_id=resp.get("remote_post_id", ""),
                      post_url=resp.get("post_url", ""),
                      published_at=resp.get("published_at") or now,
                      visibility=resp.get("visibility", "public"))
            self._event(publication_id, "publication_public",
                        {"post_url": resp.get("post_url", "")})
            return {"status": "public",
                    "post_url": resp.get("post_url", "")}
        if remote in ("not_found",):
            self._set(publication_id, status="requested",
                      last_error="no_remote_effect")
            return {"status": "requested", "action": "safe_to_resubmit"}
        local = {"accepted": "uploading", "queued": "uploading",
                 "uploading": "uploading",
                 "processing": "processing"}.get(remote, remote)
        if local in {s for s in TERMINAL} | {"uploading", "processing",
                                            "unknown", "failed"}:
            self._set(publication_id, status=local,
                      request_id=resp.get("request_id",
                                          p.get("request_id", "")))
        return {"status": local}

    def retry(self, publication_id, *, video_path="", now=""):
        """Reconcile first; resubmit only when the provider shows no
        effect. The same idempotency key dedups a double submission."""
        out = self.reconcile(publication_id, now=now)
        if out["status"] != "requested":
            return out
        return self.publish(publication_id, video_path=video_path,
                            now=now)

    # -------------------------------------------------------- manual --

    def register_manual(self, publication_id, *, variant_plan_id,
                        final_sha256, platform, account_id,
                        remote_post_id, published_at, visibility="",
                        metadata=None, horizon_policy=None, now="",
                        verify=True):
        """Manual lane: register an actual post made by a human. The
        post identity is verified against the provider when a publisher
        is attached; one post may map to exactly one variant/final."""
        now = now or _now()
        if platform not in MANUAL_PLATFORMS:
            raise ContractError("unknown_platform", "platform", platform)
        self._account(platform, account_id)
        clash = self._post_owner(platform, remote_post_id)
        if clash and clash != publication_id:
            raise ContractError("post_mapping_conflict",
                                "remote_post_id", remote_post_id)
        post = None
        if verify and self.publisher is not None:
            post = self.publisher.verify_post(remote_post_id)
            if post is None:
                raise ContractError("post_not_found",
                                    "remote_post_id", remote_post_id)
            if post.get("status") != "public":
                raise ContractError("post_not_public",
                                    "remote_post_id", remote_post_id)
            if post.get("account_id") and \
                    post["account_id"] != self.accounts.get(
                        f"{platform}:{account_id}"):
                raise ContractError("post_wrong_account",
                                    "remote_post_id", remote_post_id)
        p = Publication(
            schema_version="publication.v1", id=publication_id,
            created_at=now, variant_plan_id=variant_plan_id,
            final_sha256=final_sha256, platform=platform,
            account_id=account_id, status="public",
            remote_post_id=remote_post_id,
            post_url=(post or {}).get("post_url",
                                      f"https://youtu.be/"
                                      f"{remote_post_id}"),
            published_at=published_at,
            visibility=visibility or (post or {}).get("visibility",
                                                     "public"),
            idempotency_key=_key(publication_id, final_sha256,
                                 platform, account_id),
            metadata=dict(metadata or {}),
            horizon_policy=dict(horizon_policy or {}), manual=True)
        p.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(p)
            u.events.append(f"publication:{publication_id}",
                            "manual_post_registered",
                            {"remote_post_id": remote_post_id})
        return p

    # ------------------------------------------------------ actions --

    def _post_action(self, p, action, payload, call):
        if self.effects is None:
            raise ContractError("authority_required", "publication_action")
        request = {"action": action, "publication_id": p["id"], "remote_post_id": p["remote_post_id"],
                   "account_id": p["account_id"], "platform": p["platform"], "payload": payload}
        aid = self.effects(request, f"{action}:{p['id']}", "publication", "upload_post", action)
        self.executor.require_request(aid, request)
        def send():
            call()
            return {"operation_id": p["remote_post_id"]}
        return self.executor.submit(aid, send)

    def update_metadata(self, publication_id, metadata, now=""):
        """Explicit live-post metadata change — separate from any
        publish/retry path."""
        p = self._get(publication_id)
        if not p or not p.get("remote_post_id"):
            raise ContractError("no_remote_post", "id", publication_id)
        self._post_action(p, "update_metadata", metadata, lambda: self.publisher.update_post(p["remote_post_id"], metadata))
        self._set(publication_id, metadata={
            **(p.get("metadata") or {}), **metadata})
        self._event(publication_id, "metadata_updated",
                    {"fields": sorted(metadata)})
        return {"status": "updated"}

    def delete_post(self, publication_id, now=""):
        """Explicit deletion. The durable record keeps its history —
        status stays public-with-deleted_at rather than vanishing."""
        now = now or _now()
        p = self._get(publication_id)
        if not p or not p.get("remote_post_id"):
            raise ContractError("no_remote_post", "id", publication_id)
        self._post_action(p, "delete", {}, lambda: self.publisher.delete_post(p["remote_post_id"]))
        self._set(publication_id, deleted_at=now)
        self._event(publication_id, "post_deleted", {})
        return {"status": "deleted", "deleted_at": now}

    def get(self, publication_id):
        return self._get(publication_id)

    def list(self):
        with self.db.uow() as u:
            rows = u.conn.execute(
                "SELECT body FROM records WHERE kind='publication'"
                " ORDER BY id").fetchall()
        return [json.loads(r[0]) for r in rows]

    # ------------------------------------------------------ guards --

    def _account(self, platform, account_id):
        key = f"{platform}:{account_id}"
        if self.accounts and key not in self.accounts:
            raise ContractError("unknown_account", "account_id", key)
        if self.accounts and not self.accounts[key]:
            raise ContractError("account_not_linked", "account_id", key)

    def _check_authorization(self, p, now):
        aid = p.get("authorization_id")
        if not aid:
            raise ContractError("publication_not_authorized",
                                "authorization_id", "")
        row = self.db.uow().records.get("authorization", aid)
        auth = json.loads(row["body"]) if row else {}
        if auth.get("status") != "authorized":
            raise ContractError("publication_not_authorized",
                                "authorization_id", aid)
        if not auth.get("publication_authorized"):
            raise ContractError("publication_not_authorized",
                                "authorization_id", aid)
        until = auth.get("valid_until")
        if until and until <= now:
            raise ContractError("authorization_expired",
                                "authorization_id", aid)

    def _check_cadence(self, p, now):
        """Block BEFORE submission if the (platform, account) already
        has max_per_day scheduled/public posts on this timezone day."""
        tz = ZoneInfo(p.get("timezone") or "UTC")
        when = p.get("scheduled_at") or now
        try:
            day = datetime.fromisoformat(
                when.replace("Z", "+00:00")).astimezone(tz).date()
        except ValueError:
            day = datetime.fromisoformat(
                now.replace("Z", "+00:00")).astimezone(tz).date()
        n = 0
        for other in self.list():
            if other["id"] == p["id"] or \
                    other["platform"] != p["platform"] or \
                    other["account_id"] != p["account_id"] or \
                    other["status"] not in ("scheduled", "public", "uploading", "processing", "unknown"):
                continue
            at = other.get("published_at") or other.get("scheduled_at") or other.get("dispatch_started_at")
            if not at:
                continue
            try:
                d = datetime.fromisoformat(
                    at.replace("Z", "+00:00")).astimezone(tz).date()
            except ValueError:
                continue
            if d == day:
                n += 1
        if n >= self.max_per_day:
            raise ContractError(
                "cadence_blocked", "scheduled_at",
                f"{p['platform']}:{p['account_id']} has {n} posts on "
                f"{day} ({tz.key}); cap {self.max_per_day}")

    def _post_owner(self, platform, remote_post_id):
        for other in self.list():
            if other["platform"] == platform and \
                    other.get("remote_post_id") == remote_post_id:
                return other["id"]
        return None

    # --------------------------------------------------------- io --

    def _get(self, publication_id):
        row = self.db.uow().records.get("publication", publication_id)
        return json.loads(row["body"]) if row else None

    def _set(self, publication_id, **fields):
        row = self.db.uow().records.get("publication", publication_id)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='publication' AND "
                "id=? AND revision=?",
                (json.dumps(body), publication_id, row["revision"]))

    def _event(self, publication_id, kind, body):
        with self.db.uow() as u:
            u.events.append(f"publication:{publication_id}", kind, body)
