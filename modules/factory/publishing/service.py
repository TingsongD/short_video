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
from ..domain.records import Publication, Record, content_hash
from dataclasses import dataclass,field

@dataclass
class PublicationIntent(Record):
    plan_hash:str=''
    request:dict=field(default_factory=dict)
    experiment_id:str=''
    experiment_revision:int=0
from ..integrations.publisher import (ACCEPTED, TERMINAL,
                                      PublishTransportError)

# Platforms the automated lane may plan for (PL-03). The real gate is
# the configured account check in _account() — an unqualified or
# unconnected destination still fails there.
PUBLISHABLE = {"youtube", "tiktok", "instagram", "facebook"}
MANUAL_PLATFORMS = {"youtube", "tiktok", "instagram", "facebook"}


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
        # Wired by bootstrap: fired once when a publication reaches a
        # provider-confirmed public state so metric checkpoints can be
        # scheduled from its actual publication time.
        self.on_public = None

    def _mark_public(self, publication_id, published_at):
        if self.on_public:
            self.on_public(self._get(publication_id))

    # ------------------------------------------------------ intent --

    def plan(self, publication_id, *, variant_plan_id, final_sha256,
             platform, account_id, metadata=None, visibility="public",
             scheduled_at="", tz="UTC", media_url="",
             horizon_policy=None, authorization_id="", now="",
             automated=True,artifact_id='',experiment_id='',
             experiment_revision=0, provider="upload_post",
             connection_id="", metadata_package_id="",
             metadata_revision=0):
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
                        manual=not automated,
                        experiment_id=experiment_id,
                        experiment_revision=experiment_revision,
                        provider=provider, connection_id=connection_id,
                        metadata_package_id=metadata_package_id,
                        metadata_revision=metadata_revision)
        p.artifact_id=artifact_id
        p.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(p)
            request=self.request(p.to_dict())
            u.records.put(PublicationIntent(schema_version='publication_intent.v1',id='intent:'+publication_id,created_at=now,
                plan_hash=content_hash(request),request=request,experiment_id=experiment_id,experiment_revision=experiment_revision))
            u.events.append(f"publication:{publication_id}",
                            "publication_planned",
                            {"platform": platform,
                             "account_id": account_id})
        return p

    def request(self,p):
        return {'publication_id':p['id'],'artifact_id':p.get('artifact_id',''),'final_sha256':p['final_sha256'],
            'platform':p['platform'],'account_id':p['account_id'],'provider_user':self.accounts.get(p['platform']+':'+p['account_id'],''),
            'metadata':p.get('metadata') or {},'visibility':p.get('visibility'),'scheduled_at':p.get('scheduled_at'),
            'timezone':p.get('timezone','UTC'),'horizon_policy':p.get('horizon_policy') or {},'action':'publish'}

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
        with self.db.uow():
            self._set(publication_id, authorization_id=authorization_id)
            self._check_authorization(self._get(publication_id),now or _now())
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
        if p["status"] in ("public", "draft", "scheduled"):
            return {"status": p["status"], "request_id": p.get("request_id", "")}
        if p.get("attempt_id") and self.executor._attempt(p['attempt_id'])['status']!='prepared':
            return self.reconcile(publication_id, now=now)
        self._check_authorization(p, now)
        from pathlib import Path
        if not video_path or not Path(video_path).is_file():raise ContractError('final_bytes_required','artifact')
        with Path(video_path).open('rb') as media: digest=hashlib.file_digest(media,'sha256').hexdigest()
        if digest!=p['final_sha256']:raise ContractError('final_bytes_changed','artifact')
        if self.effects is None:
            raise ContractError("authority_required", "publication")
        request = self.request(p)
        with self.db.uow():
            self._check_cadence(p, now)
            aid = self.effects(request, f"publish:{publication_id}", "publication", p.get('provider','upload_post'), "upload")
            self.executor.require_request(aid, request)
            self._set(publication_id, attempt_id=aid, request_id=p['idempotency_key'],status="uploading", dispatch_started_at=now)
        meta = p.get("metadata") or {}
        def upload():
            resp = self.publisher.upload(
                video_path=video_path,
                title=meta.get("title", ""),
                description=meta.get("description", ""),
                platforms=(p["platform"],),
                visibility=p.get("visibility", "public"),
                schedule_date=p.get("scheduled_at", ""),
                user=self.accounts.get(
                    f"{p['platform']}:{p['account_id']}", ""),
                idempotency_key=p["idempotency_key"],
                extra_fields={"hashtags": ",".join(meta.get("hashtags", [])), 'timezone':p.get('timezone','UTC')})
            publication_status=resp.get('status','unknown')
            state=('succeeded' if publication_status in ('public','draft','scheduled') else
                   'failed' if publication_status=='failed' else
                   'accepted' if publication_status in ACCEPTED else 'unknown')
            return dict(resp, operation_id=resp["request_id"],status=state,publication_status=publication_status)
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

    # ---------------------------------------------- remote cancel --

    def cancel_remote(self, publication_id, now=""):
        """§10 matrix: cancel a provider-side scheduled job. Outcomes
        are provider-confirmed, never inferred — a slot that raced to
        live is 'already_public', a failed cancel is 'cancel_failed'."""
        now = now or _now()
        p = self._get(publication_id)
        if p is None:
            raise ContractError("unknown_publication", "id",
                                publication_id)
        if self.publisher is None:
            raise ContractError("no_publisher", "platform",
                                p["platform"])
        if p["status"] == "public":
            return {"outcome": "already_public",
                    "publication_id": publication_id}
        if p["status"] in ("draft", "failed", "cancelled",
                           "requested"):
            return {"outcome": "not_scheduled",
                    "publication_id": publication_id,
                    "status": p["status"]}
        job_id = p.get("remote_schedule_id") or p.get("job_id")
        if not job_id:
            self.reconcile(publication_id, now=now)
            p = self._get(publication_id)
            job_id = p.get("remote_schedule_id") or p.get("job_id")
        if not job_id:
            self._event(publication_id, "remote_cancel_unknown",
                        {"reason": "no_remote_job_id"})
            return {"outcome": "unknown", "reason": "no_remote_job_id",
                    "publication_id": publication_id}
        try:
            resp = self.publisher.cancel_schedule(job_id)
        except PublishTransportError as e:
            try:
                self.reconcile(publication_id, now=now)
                if self._get(publication_id)["status"] == "public":
                    return {"outcome": "already_public",
                            "publication_id": publication_id}
            except PublishTransportError:
                pass
            self._event(publication_id, "remote_cancel_failed",
                        {"job_id": job_id, "error": str(e)})
            return {"outcome": "cancel_failed", "error": str(e),
                    "publication_id": publication_id}
        # The response body is provider truth — a refused or denied
        # cancel is never reported as a success (§10 outcome matrix).
        if isinstance(resp, dict) and (
                resp.get("cancelled") is False or
                resp.get("success") is False):
            reason = (resp.get("reason") or resp.get("error")
                      or "refused")
            if reason == "already_published":
                try:
                    self.reconcile(publication_id, now=now)
                except PublishTransportError:
                    pass
                if self._get(publication_id)["status"] == "public":
                    return {"outcome": "already_public",
                            "publication_id": publication_id}
            self._event(publication_id, "remote_cancel_failed",
                        {"job_id": job_id, "reason": reason})
            return {"outcome": "cancel_failed", "reason": reason,
                    "publication_id": publication_id}
        try:
            self.reconcile(publication_id, now=now)
            after = self._get(publication_id)["status"]
            if after == "public":
                return {"outcome": "already_public",
                        "publication_id": publication_id}
            if after == "scheduled":
                # The provider acknowledged but the slot still shows
                # scheduled — the cancel is unconfirmed, not done.
                self._event(publication_id,
                            "remote_cancel_unconfirmed",
                            {"job_id": job_id})
                return {"outcome": "unknown",
                        "reason": "remote_still_scheduled",
                        "publication_id": publication_id}
        except PublishTransportError:
            pass
        self._set(publication_id, status="cancelled")
        self._event(publication_id, "remote_cancelled",
                    {"job_id": job_id})
        return {"outcome": "cancelled",
                "publication_id": publication_id}

    def _apply(self, publication_id, resp, now):
        status = resp.get("publication_status",resp.get("status", "accepted"))
        if status=='public' and self._get(publication_id).get('visibility')!='public':status='draft'
        fields = {"request_id": resp.get("request_id", "")}
        if resp.get('job_id'):fields['job_id']=resp['job_id']
        fields['platform_results']=resp.get('platform_results',[])
        became_public=False
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
            became_public=True
        elif status in TERMINAL:
            fields["status"] = status
            if status == "scheduled":
                fields["scheduled_at"] = resp.get(
                    "scheduled_at", fields.get("scheduled_at", ""))
        self._set(publication_id, **fields)
        if became_public:self._mark_public(publication_id,fields["published_at"])
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
                resp = self.publisher.status(p["request_id"],platform=p['platform'],job_id=p.get('job_id',''))
            else:
                found = self.publisher.find_by_idempotency_key(
                    p["idempotency_key"],platform=p['platform'])
                if found is None:
                    self._set(publication_id, status="unknown", last_error="no_remote_trace")
                    return {"status": "unknown", "action": "reconcile_or_review_evidence"}
                resp = found
        except PublishTransportError:
            self._set(publication_id, status="unknown")
            return {"status": "unknown",
                    "action": "retry_reconcile_later"}
        remote = resp.get("status", "unknown")
        if p.get('visibility')!='public' and remote=='public':remote='draft'
        if p.get('scheduled_at') and remote in ('accepted','queued','processing'):remote='scheduled'
        if p.get('attempt_id'):
            state='succeeded' if remote in ('public','draft','scheduled') else 'failed' if remote=='failed' else 'unknown' if remote=='unknown' else 'accepted'
            self.executor._attach_remote(p['attempt_id'],p.get('request_id') or p['idempotency_key'],state,'publication_observed')
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
            self._mark_public(publication_id,
                              resp.get("published_at") or now)
            return {"status": "public",
                    "post_url": resp.get("post_url", "")}
        if remote in ('not_found',):remote='unknown'
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
            if post.get("account_id") != self.accounts.get(
                        f"{platform}:{account_id}"):
                raise ContractError("post_wrong_account",
                                    "remote_post_id", remote_post_id)
            if post.get('platform')!=platform or post.get('remote_post_id')!=remote_post_id or not post.get('published_at') or not post.get('post_url','').startswith('https://'):
                raise ContractError('post_identity_unverified','remote_post_id')
        # The publication inherits the variant's experiment identity —
        # revision-scoped learning depends on it.
        vp = self.db.uow().records.get("variantplan", variant_plan_id)
        vpb = json.loads(vp["body"]) if vp else {}
        p = Publication(
            schema_version="publication.v1", id=publication_id,
            created_at=now, variant_plan_id=variant_plan_id,
            final_sha256=final_sha256, platform=platform,
            account_id=account_id, status="public" if post else 'unverified',
            remote_post_id=remote_post_id,
            post_url=(post or {}).get("post_url",''),
            published_at=(post or {}).get('published_at',''),
            visibility=visibility or (post or {}).get("visibility",
                                                     "public"),
            idempotency_key=_key(publication_id, final_sha256,
                                 platform, account_id),
            metadata=dict(metadata or {}),
            horizon_policy=dict(horizon_policy or {}), manual=True,
            experiment_id=vpb.get("experiment_id",""),
            experiment_revision=vpb.get("experiment_revision",0))
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
        self._post_action(p, "update_metadata", metadata, lambda: self.publisher.update_post(p['remote_post_id'], metadata,platform=p['platform'],user=self.accounts[p['platform']+':'+p['account_id']]))
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
        self._post_action(p, "delete", {}, lambda: self.publisher.delete_post(p['remote_post_id'],platform=p['platform'],user=self.accounts[p['platform']+':'+p['account_id']]))
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
        if key not in self.accounts:
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
        if until and datetime.fromisoformat(until.replace('Z','+00:00')) <= datetime.fromisoformat(now.replace('Z','+00:00')):
            raise ContractError("authorization_expired",
                                "authorization_id", aid)
        from ..execution.effects import EffectService
        effect=EffectService(self.db,clock=lambda:datetime.fromisoformat(now.replace('Z','+00:00')))
        scoped=effect._scope(aid)
        op=scoped.binding['operations'].get('publish',{})
        if scoped.binding['kind']!='publicationintent' or scoped.binding['id']!='intent:'+p['id'] or op.get('request')!=self.request(p) or op.get('account')!=p['account_id']:
            raise ContractError('publication_scope_mismatch','authorization_id')

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
