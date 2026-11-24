"""One-shot trusted key provisioning. No upstream requests and no secret output."""

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request

DATA_ROUTES = ["/v1/models", "/models", "/v1/chat/completions", "/chat/completions"]
# 1.96.0 virtual-key auth supports prefix matching, not {model_id} templates.
# Keep this within model management; the proxy policy constrains mutations.
ADMIN_ROUTES = ["/model/*"]
MANAGER_USER = "dramaforge-model-manager"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def main():
    master = os.environ.get("LITELLM_MASTER_KEY", "")
    data_key = os.environ.get("LITELLM_API_KEY", "")
    admin_key = os.environ.get("LITELLM_MODEL_ADMIN_KEY", "")
    if not all((master, data_key, admin_key)):
        print("LLM service keys not configured; model management remains unavailable")
        return
    if len({master, data_key, admin_key}) != 3:
        raise RuntimeError("management, data and master credentials must be distinct")
    root = os.environ.get("LITELLM_BOOTSTRAP_PROXY_URL", "http://127.0.0.1:4000").rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(path, body=None):
        request = urllib.request.Request(root + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + master})
        try:
            with opener.open(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            # Do not log body/headers: the management API can return secret material.
            return exc.code, None

    for key, routes, alias, user_id in (
        (data_key, DATA_ROUTES, "dramaforge-data", None),
        (admin_key, ADMIN_ROUTES, "dramaforge-model-admin", MANAGER_USER),
    ):
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        query = urllib.parse.urlencode({"key_hash": key_hash, "return_full_object": "true"})
        status, listed = call("/key/list?" + query)
        if status != 200 or not isinstance(listed, dict):
            raise RuntimeError("cannot verify service key metadata")
        rows = listed.get("keys", [])
        if rows:
            if len(rows) != 1 or set(rows[0].get("allowed_routes") or []) != set(routes):
                raise RuntimeError("existing service key permissions require operator review")
            if user_id is not None and rows[0].get("user_id") != user_id:
                raise RuntimeError("model management key has an unexpected owner")
            continue
        if user_id:
            status, _ = call("/user/new", {"user_id": user_id, "user_role": "proxy_admin",
                                           "auto_create_key": False})
            if status not in (200, 409):
                raise RuntimeError("cannot provision the model-management service identity")
            if status == 409:
                status, existing = call("/user/info?" + urllib.parse.urlencode({"user_id": user_id}))
                if status != 200 or existing.get("user_info", existing).get("user_role") != "proxy_admin":
                    raise RuntimeError("existing management service identity requires operator review")
        status, _ = call("/key/generate", {"key": key, "key_alias": alias + "-" + key_hash[:12], "user_id": user_id,
                                          "key_type": "default", "models": [],
                                          "allowed_routes": routes})
        if status != 200:
            raise RuntimeError("key provisioning outcome requires metadata verification; not retried")
    print("Restricted model-management and data service keys verified")


if __name__ == "__main__":
    main()
