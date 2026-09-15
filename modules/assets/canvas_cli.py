"""Official Canvas CLI boundary. No raw HTTP, cookie access, or automatic login.

Only selected public fields leave this boundary. In particular command errors
never include argv/stdout/stderr, which can contain a credit confirmation token.
"""
import json
import subprocess


class CanvasError(RuntimeError):
    def __init__(self, code, action=None, request_id=None):
        self.code, self.action, self.request_id = code, action, request_id
        super().__init__(f"Canvas: {code}" + (f"; next: {action}" if action else "")
                         + (f"; request: {request_id}" if request_id else ""))


class CanvasCLI:
    def __init__(self, executable="dreamina-canvas", profile="default", region="cn",
                 runner=None):
        self.executable, self.profile, self.region = executable, profile, region
        self.runner = runner or subprocess.run

    def call(self, *args, timeout=60, incomplete=False):
        cmd = [self.executable, "--format", "json", "--non-interactive",
               "--profile", self.profile, "--region", self.region, *map(str, args)]
        try:
            result = self.runner(cmd, capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise CanvasError("cli_missing", "install dreamina-canvas") from None
        except subprocess.TimeoutExpired:
            raise CanvasError("transport_timeout", "inspect saved operation; do not resubmit") from None
        except OSError:
            raise CanvasError("cli_execution_failed", "check executable permissions") from None
        try:
            doc = json.loads(result.stdout)
            if not isinstance(doc, dict) or doc.get("schemaVersion") != "1":
                raise ValueError()
            if type(doc.get("ok")) is not bool:
                raise ValueError()
        except (ValueError, TypeError):
            raise CanvasError("invalid_response", "inspect saved operation; do not resubmit") from None
        if result.returncode == 20 and incomplete:
            data = doc.get("partialData") or doc.get("data") or {}
            if not isinstance(data, dict):
                raise CanvasError("invalid_response")
            return data
        if result.returncode or not doc["ok"]:
            e = doc.get("error") or {}
            raise CanvasError(e.get("code", f"exit_{result.returncode}"),
                              e.get("requiredAction"), doc.get("meta", {}).get("requestId"))
        data = doc.get("data")
        if not isinstance(data, dict):
            raise CanvasError("missing_data")
        return data

    def doctor(self):
        version = self.call("version")
        protocol = self.call("schema")
        required = {
            "canvas create": {"project-id"},
            "canvas ls": {"cursor"},
            "node create video": {"node-id", "update-id", "duration", "model", "mode"},
            "node create image": {"node-id", "update-id", "model", "mode"},
            "node quote": {"node-id"},
            "node confirm": {"credit-ceiling"},
            "node run": {"submit-id", "credit-token"},
            "node show": {"node-id"},
            "operation status": {"project-id"},
            "operation wait": {"timeout"},
            "resource download": {"output"},
        }
        commands = {}
        def visit(node, prefix=""):
            path = (prefix + " " + node.get("name", "")).strip()
            commands[path] = {f["name"] for f in node.get("flags", [])}
            for child in node.get("subcommands", []):
                visit(child, path)
        for node in protocol.get("subcommands", []):
            visit(node)
        if any(not flags <= commands.get(path, set()) for path, flags in required.items()):
            raise CanvasError("unsupported_cli_schema", "update or review the CLI integration")
        local = self.call("auth", "status")
        if not local.get("loggedIn"):
            raise CanvasError("login_required", "dreamina-canvas auth login")
        if local.get("region") != self.region or local.get("environment") != "prod":
            raise CanvasError("account_region_mismatch")
        account = self.call("auth", "account")
        if not account.get("userId"):
            raise CanvasError("account_not_verified")
        return {"version": version.get("version"), "commit": version.get("commit"),
                "profile": self.profile, "region": local["region"],
                "environment": local["environment"], "userId": account["userId"],
                "isVip": account.get("isVip"), "vipLevel": account.get("vipLevel")}

    def catalog(self, kind):
        items = self.call("model", "list", "--type", kind).get("items")
        if not isinstance(items, list) or not items:
            raise CanvasError("model_catalog_empty")
        return items

    def find_canvas(self, project_id):
        cursor = None
        while True:
            args = ["canvas", "ls", "--limit", "100"]
            if cursor:
                args += ["--cursor", cursor]
            data = self.call(*args)
            for item in data.get("items", []):
                if item.get("projectId") == project_id:
                    return item
            if not data.get("hasMore"):
                return None
            next_cursor = data.get("nextCursor")
            if not next_cursor or next_cursor == cursor:
                raise CanvasError("invalid_canvas_pagination")
            cursor = next_cursor

    def node(self, project_id, node_id):
        data = self.call("node", "show", "--project-id", project_id, "--node-id", node_id)
        nodes = data.get("nodes", [])
        if len(nodes) != 1 or nodes[0].get("result") != "FOUND":
            raise CanvasError("node_not_found", "inspect the existing canvas")
        node = nodes[0].get("node", {})
        if node.get("nodeId") != node_id:
            raise CanvasError("node_identity_mismatch")
        return node

    def quote(self, project_id, node_ids):
        args = ["node", "quote", "--project-id", project_id]
        for node_id in node_ids:
            args += ["--node-id", node_id]
        data = self.call(*args)
        items = data.get("items", [])
        if (len(items) != len(node_ids) or {i.get("nodeId") for i in items} != set(node_ids)
                or data.get("confirmable") is False
                or any(i.get("error") or type(i.get("maxCredits")) is not int
                       or i["maxCredits"] < 0 for i in items)):
            raise CanvasError("quote_incomplete", "resolve unquotable shots before approval")
        total = sum(i["maxCredits"] for i in items)
        if type(data.get("totalMaxCredits")) is not int or data["totalMaxCredits"] != total:
            raise CanvasError("quote_total_mismatch")
        return {"items": [{"nodeId": i["nodeId"], "maxCredits": i["maxCredits"]}
                          for i in items], "totalMaxCredits": total,
                "draftVersion": data.get("draftVersion")}

    def submit(self, project_id, node_id, submit_id, ceiling):
        approved = self.call("node", "confirm", "--project-id", project_id,
                             "--node-id", node_id, "--credit-ceiling", ceiling)
        token = approved.get("creditConfirmationToken")
        if not token or approved.get("creditCeiling") != ceiling:
            raise CanvasError("invalid_credit_confirmation")
        # Never return or persist the token; the exception boundary omits argv.
        return self.call("node", "run", "--project-id", project_id,
                         "--node-id", node_id, "--submit-id", submit_id,
                         "--credit-token", token)
