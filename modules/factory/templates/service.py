"""Template service (F13 checklist 5–6): persist, version, preview and
inspect templates. Lifecycle (candidate/proven/retired) is managed
here; promotion evidence is F33's job — this service only records the
status, it never invents proof."""
import json

from ..domain.errors import ContractError
from ..domain.records import FormatTemplate, Slot
from ..store.uow import utcnow
from .authoring import author_from_blueprint
from .capabilities import capability_report
from .validate import validate_template


def load_template(row):
    d = json.loads(row["body"])
    d["slots"] = [Slot(**s) for s in d.get("slots") or []]
    return FormatTemplate(**d)


class TemplateService:
    def __init__(self, db):
        self.db = db

    def author(self, blueprint, template_id, validate=True):
        tpl = author_from_blueprint(blueprint, template_id)
        if validate:
            problems = validate_template(
                tpl, total_frames=blueprint.target_frames)
            if problems:
                raise ContractError("template_invalid", "slots",
                                    json.dumps(problems)[:200])
        tpl.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(tpl)
            u.events.append(f"template:{tpl.id}", "authored",
                            {"from_blueprint": tpl.derived_from_blueprint,
                             "slots": len(tpl.slots)})
        return tpl

    def get(self, template_id, revision=None):
        row = self.db.uow().records.get("formattemplate",
                                        template_id, revision=revision)
        if row is None:
            raise ContractError("unknown_template", "id", template_id)
        return load_template(row)

    def revise(self, template_id, mutate, reason=""):
        """Versioned edit: new revision row; the previous revision stays
        readable so plans bound to it keep their appearance."""
        row = self.db.uow().records.get("formattemplate", template_id)
        if row is None:
            raise ContractError("unknown_template", "id", template_id)
        tpl = load_template(row)
        body = json.loads(row["body"])
        body = mutate(dict(body)) or body
        body["revision"] = row["revision"] + 1
        child = load_template({"body": json.dumps(body)})
        child.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(child)
            u.events.append(f"template:{template_id}", "revised",
                            {"revision": child.revision,
                             "reason": reason})
        return child

    def set_status(self, template_id, status):
        """candidate|proven|retired lifecycle — status only; promotion
        evidence is recorded by F33 decisions, not here."""
        if status not in ("candidate", "proven", "retired"):
            raise ContractError("bad_status", "status", status)
        row = self.db.uow().records.get("formattemplate", template_id)
        body = json.loads(row["body"])
        body["status"] = status
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='formattemplate' "
                "AND id=? AND revision=?",
                (json.dumps(body), template_id, row["revision"]))
            u.events.append(f"template:{template_id}", "status",
                            {"status": status})

    def plans_bound_to(self, template_id, revision):
        """Plans referencing this template revision — for compatibility
        checks before revising."""
        bound = []
        for row in self.db.conn.execute(
                "SELECT id, body FROM records WHERE kind="
                "'experimentrevision'").fetchall():
            body = json.loads(row["body"])
            ref = body.get("template_ref") or {}
            if isinstance(ref, str):
                rid, separator, rev = ref.rpartition("@")
                if not separator or not rev.isdigit():
                    continue
                ref = {"id": rid, "revision": int(rev)}
            if ref.get("id") == template_id and \
                    ref.get("revision") == revision:
                bound.append(row["id"])
        return bound

    # ------------------------------------------------------- preview

    def preview(self, template_id):
        """Readable inspection view + a fixture-style composition spec
        a renderer could consume (F13 checklist 6)."""
        tpl = self.get(template_id)
        cap = capability_report(tpl.slots)
        spec = {"template": tpl.id, "revision": tpl.revision,
                "renderer": cap["preferred"],
                "slots": [{"id": s.id, "kind": s.kind,
                           "frames": s.frames,
                           "min": s.min_frames, "max": s.max_frames,
                           "reference": s.required_reference,
                           "effects": s.effects,
                           "transition": s.transition_out}
                          for s in tpl.slots],
                "constraints": tpl.constraints,
                "unsupported": cap["unsupported"]}
        lines = [f"template {tpl.id} rev{tpl.revision} "
                 f"({tpl.status}) renderer→{cap['preferred']}"]
        cursor = 0
        for s in tpl.slots:
            lines.append(
                f"  [{cursor:>4}-{cursor + s.frames:>4}) {s.kind:<10}"
                f" {s.id} fx={','.join(s.effects) or 'none'}"
                f" →{s.transition_out}")
            cursor += s.frames
        if cap["unsupported"]:
            lines.append(f"  UNSUPPORTED: {cap['unsupported']}")
        return {"spec": spec, "view": "\n".join(lines)}
