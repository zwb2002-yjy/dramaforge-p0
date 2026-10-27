#!/usr/bin/env python3
"""Exercise backup/restore and namespace recreation on the synthetic quality stack only."""

from __future__ import annotations

import argparse
import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, body: str | None = None) -> str:
    result = subprocess.run(
        args, input=body, text=True, capture_output=True, timeout=240, check=False
    )
    if result.returncode:
        raise RuntimeError(
            f"quality command failed: {args[:4]}: {result.stderr[-1500:]}"
        )
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project")
    parser.add_argument("--compose-file", action="append")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / "tmp") or output.exists():
        raise ValueError("evidence requires a new directory under repository tmp")
    output.mkdir(parents=True)
    compose = ["docker", "compose"]
    if args.project:
        compose.extend(["-p", args.project])
    for file in args.compose_file or ["docker-compose.quality.yml"]:
        compose.extend(["-f", file])

    def container(service: str) -> str:
        identifier = run([*compose, "ps", "-q", service])
        info = json.loads(run(["docker", "inspect", identifier]))[0]
        if info["Config"]["Labels"].get("com.docker.compose.service") != service:
            raise ValueError("unexpected quality service ownership")
        return identifier

    proxy = container("litellm-policy-quality")
    database = container("litellm-db-quality")
    guard = container("litellm-policy-network-quality")
    before_namespace = json.loads(run(["docker", "inspect", proxy]))[0]["HostConfig"][
        "NetworkMode"
    ]
    assert before_namespace == f"container:{guard}"
    identifier = str(uuid.uuid4())
    alias = "quality-recovery-" + identifier
    (output / "reference.json").write_text(
        json.dumps({"id": identifier, "alias": alias}), encoding="utf-8"
    )
    request_code = """
import json, os, urllib.request
assert os.environ['LITELLM_MASTER_KEY']=='sk-quality-policy-master-key', 'quality stack required'
def call(path, body=None):
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request('http://127.0.0.1:4000'+path,data=data,headers={
      'Content-Type':'application/json','Authorization':'Bearer '+os.environ['LITELLM_MASTER_KEY']})
    with urllib.request.urlopen(req,timeout=15) as r: return json.load(r)
"""
    create = {
        "model_name": alias,
        "litellm_params": {
            "model": f"openai/{identifier}",
            "api_base": "http://litellm-mock-quality:9000/success/v1",
            "api_key": "synthetic-recovery-key",
            "max_retries": 0,
        },
        "model_info": {"id": identifier},
    }
    run(
        ["docker", "exec", "-i", proxy, "python", "-"],
        body=request_code
        + f"assert call('/model/new',json.loads({json.dumps(create)!r}))\n",
    )

    def verify(active_proxy: str) -> dict[str, object]:
        code = (
            request_code
            + f"""
rows=call('/model/info?litellm_model_id={identifier}')['data']
assert len(rows)==1 and rows[0]['model_info']['id']=='{identifier}'
result=call('/v1/chat/completions',{{'model':'{alias}','messages':[{{'role':'user','content':'synthetic'}}]}})
assert result['choices'][0]['message']['content']=='synthetic response'
events=json.load(urllib.request.urlopen('http://litellm-mock-quality:9000/events'))
print(json.dumps({{'deployment_id':'{identifier}','matching_upstream_requests':sum(e['model']=='{identifier}' for e in events)}}))
"""
        )
        return json.loads(
            run(["docker", "exec", "-i", active_proxy, "python", "-"], body=code)
        )

    original = verify(proxy)
    run(
        [
            "docker",
            "exec",
            database,
            "pg_dump",
            "-U",
            "litellm",
            "-d",
            "litellm",
            "-Fc",
            "-f",
            "/tmp/quality-recovery.dump",
        ]
    )
    run(
        [
            "docker",
            "cp",
            f"{database}:/tmp/quality-recovery.dump",
            str(output / "proxy-db.dump"),
        ]
    )
    restored_name = "quality_restore_" + uuid.uuid4().hex[:12]
    run(["docker", "exec", database, "createdb", "-U", "litellm", restored_name])
    run(
        [
            "docker",
            "exec",
            database,
            "pg_restore",
            "-U",
            "litellm",
            "-d",
            restored_name,
            "/tmp/quality-recovery.dump",
        ]
    )
    override = output / "restore-compose.json"
    override.write_text(
        json.dumps(
            {
                "services": {
                    "litellm-policy-quality": {
                        "environment": {
                            "DATABASE_URL": "postgresql://litellm:quality-litellm-db-password@litellm-db-quality:5432/"
                            + restored_name,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    run(
        [
            *compose,
            "-f",
            str(override),
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--force-recreate",
            "--wait",
            "litellm-policy-quality",
        ]
    )
    restored = verify(container("litellm-policy-quality"))
    run(
        [
            *compose,
            "up",
            "-d",
            "--no-deps",
            "--no-build",
            "--force-recreate",
            "--wait",
            "litellm-policy-network-quality",
            "litellm-policy-quality",
        ]
    )
    proxy = container("litellm-policy-quality")
    guard = container("litellm-policy-network-quality")
    after_namespace = json.loads(run(["docker", "inspect", proxy]))[0]["HostConfig"][
        "NetworkMode"
    ]
    assert (
        after_namespace == f"container:{guard}" and after_namespace != before_namespace
    )
    recreated = verify(proxy)
    assert [
        item["matching_upstream_requests"] for item in (original, restored, recreated)
    ] == [1, 2, 3]
    current_database = run(
        [
            "docker",
            "exec",
            proxy,
            "python",
            "-c",
            "import os,urllib.parse;print(urllib.parse.urlsplit(os.environ['DATABASE_URL']).path)",
        ]
    )
    assert current_database == "/litellm", (
        "restore experiment must leave the original test DB active"
    )
    # Only the unique DB created by this invocation. Namespace replacement can
    # leave idle old TCP sessions until PostgreSQL's keepalive timeout.
    run(
        [
            "docker",
            "exec",
            database,
            "dropdb",
            "--force",
            "-U",
            "litellm",
            restored_name,
        ]
    )
    summary = {
        "original": original,
        "restored": restored,
        "namespace_recreated": recreated,
        "stable_salt": True,
        "restored_test_database_removed": restored_name,
        "namespace_changed": True,
        "real_provider_requests": 0,
    }
    (output / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
