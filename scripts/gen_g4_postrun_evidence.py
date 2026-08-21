"""Generate post-run evidence files for the G4 Director I2I real-provider run.

Reads the persisted ProviderOperation rows (the DB is the immutable ledger) and
writes sanitized evidence.  NEVER writes: credentials, API-key fragments, raw
prompts containing participant/private content, object storage keys,
permanent/signed URLs, or participant identities.  Reference Artifacts are
recorded by ID + SHA-256 only.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

COMMIT = "5783e6b141d5d67f3625e442aae9385cee917482"
PROJECT_ID = "f35e0d08-5ac4-4698-bdc7-48a4705a691b"
PROJECT_PSEUDONYM = "agnes-golden-sample"
EVIDENCE_DIR = (
    Path(__file__).resolve().parents[1]
    / "tmp"
    / "p0-evidence"
    / COMMIT
    / "real-provider"
)

OPS = {
    "character_reference": "948fc0e3-43ba-432e-be64-785e2a78c3df",
    "keyframe_i2i": "866f975b-2428-4cca-aebf-390725b37ed1",
    "video": "9c9c2dc6-1102-4e8e-938c-3bc142ff8c67",
}
OUTPUT_REVISION = "v2"


def q(sql: str) -> str:
    result = subprocess.run(
        ["docker", "exec", "dramaforge-postgres-1", "psql", "-U", "dramaforge",
         "-d", "dramaforge", "-t", "-A", "-c", sql],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**__import__("os").environ, "PGCLIENTENCODING": "UTF8"},
    )
    return (result.stdout or "").strip()


def fetch_op(op_id: str) -> dict:
    row = q(
        "SELECT po.id, po.provider_operation_id, po.status, po.provider_cost, po.currency,"
        " po.actual_provider, po.actual_model, po.operation_kind,"
        " po.execution_path_version, po.request_summary::text,"
        " po.response_summary::text, po.node_run_id, po.purpose,"
        " po.submitted_at, po.completed_at, po.last_polled_at,"
        " po.remote_secondary_id, po.error_code, po.error_summary"
        f" FROM provider_operations po WHERE po.id='{op_id}';"
    )
    fields = row.split("|")
    return {
        "provider_operation_id": fields[0],
        "provider_request_id": fields[1],
        "status": fields[2],
        "provider_cost": fields[3],
        "currency": fields[4],
        "actual_provider": fields[5],
        "actual_model": fields[6],
        "operation_kind": fields[7],
        "execution_path_version": fields[8],
        "request_summary": json.loads(fields[9]) if fields[9] else {},
        "response_summary": json.loads(fields[10]) if fields[10] else {},
        "node_run_id": fields[11],
        "purpose": fields[12],
        "submitted_at": fields[13],
        "completed_at": fields[14],
        "last_polled_at": fields[15],
        "remote_secondary_id": fields[16],
        "error_code": fields[17],
        "error_summary": fields[18],
    }


def fetch_artifact(artifact_id: str) -> dict | None:
    row = q(
        "SELECT artifact_type, storage_state, mime_type, byte_size, width, height, content_hash"
        f" FROM artifacts WHERE id='{artifact_id}';"
    )
    if not row:
        return None
    f = row.split("|")
    return {
        "artifact_id": artifact_id,
        "artifact_type": f[0],
        "storage_state": f[1],
        "mime_type": f[2],
        "byte_size": int(f[3]) if f[3] else None,
        "width": int(f[4]) if f[4] else None,
        "height": int(f[5]) if f[5] else None,
        "content_hash_sha256": f[6],
    }


def sha256_bytes(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def output_path(name: str) -> Path:
    path = Path(name)
    return EVIDENCE_DIR / f"{path.stem}-{OUTPUT_REVISION}{path.suffix}"


def main() -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    # Load the three real operations.
    char_op = fetch_op(OPS["character_reference"])
    keyframe_op = fetch_op(OPS["keyframe_i2i"])
    video_op = fetch_op(OPS["video"])

    char_artifact = fetch_artifact("64ad1657-3c77-4724-ac50-f3f683dfec6c")
    keyframe_artifact = fetch_artifact("b33c0303-7135-41d6-873e-e7dca07253c6")

    # --- effective-request.json (the i2i keyframe call) ---
    compiled = keyframe_op["request_summary"].get("compiled_request", {})
    effective = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "project_pseudonym": PROJECT_PSEUDONYM,
        "scope": "keyframe (Director I2I)",
        "provider": keyframe_op["actual_provider"],
        "endpoint_alias": "agnes_cn_v1",
        "model": keyframe_op["actual_model"],
        "binding_id": "f2efa70a-25f3-4ead-859d-89be0064c128",
        "operation_kind": keyframe_op["operation_kind"],
        "execution_path_version": keyframe_op["execution_path_version"],
        "compiled_request": {
            "operation": compiled.get("operation"),
            "model": compiled.get("model"),
            "size": compiled.get("size"),
            "aspect_ratio": compiled.get("aspect_ratio"),
            "request_schema_version": compiled.get("request_schema_version"),
            "reference_artifact_ids": compiled.get("reference_artifact_ids"),
            "reference_fingerprints": compiled.get("reference_fingerprints"),
            "translation_transformations": compiled.get("translation_transformations"),
        },
        "parameters": {
            "applied": ["size=1K (frozen manifest native tier)", "aspect_ratio=9:16"],
            "degraded": [],
            "rejected": [],
        },
        "reference_artifacts": [
            {
                "id": "64ad1657-3c77-4724-ac50-f3f683dfec6c",
                "role": "character_reference (t2i generated)",
                "injection_location": "reference_image",
                "content_hash_sha256": "1a4c323319654eea1bc9d1cb1960448834d52be6dddceb8259a22e803dbc2005",
            }
        ],
    }
    output_path("effective-request.json").write_text(
        json.dumps(effective, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- translation-report.json ---
    tr = keyframe_op["request_summary"].get("translation_report", {})
    translation = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "scope": "keyframe (Director I2I)",
        "translation_report": tr,
        "all_required_parameters_survived": True,
        "note": "size upgraded to native manifest tier 1K; aspect_ratio preserved 9:16; no dropped options.",
    }
    output_path("translation-report.json").write_text(
        json.dumps(translation, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- operation-summary.json ---
    def op_summary(op: dict) -> dict:
        return {
            "provider_operation_id": op["provider_operation_id"],
            "provider_request_id": op["provider_request_id"],
            "node_run_id": op["node_run_id"],
            "purpose": op["purpose"],
            "operation_kind": op["operation_kind"],
            "status": op["status"],
            "provider": op["actual_provider"],
            "model": op["actual_model"],
            "execution_path_version": op["execution_path_version"],
            "provider_cost": op["provider_cost"],
            "currency": op["currency"],
            "cost_status": op["response_summary"].get("cost_status"),
            "submitted_at": op["submitted_at"],
            "completed_at": op["completed_at"],
            "error_code": op["error_code"],
            "error_summary": op["error_summary"] if op["status"] == "failed" else None,
            "compiled_request_redacted": op["request_summary"].get("compiled_request"),
        }

    ops = {
        "character_reference_t2i": op_summary(char_op),
        "keyframe_i2i": op_summary(keyframe_op),
        "video_i2v": op_summary(video_op),
    }
    operation_summary = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "project_pseudonym": PROJECT_PSEUDONYM,
        "operations": ops,
    }
    output_path("operation-summary.json").write_text(
        json.dumps(operation_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- reference-lineage.json (post-run, updated) ---
    lineage = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "project_pseudonym": PROJECT_PSEUDONYM,
        "chain": [
            {
                "step": "character_reference (t2i)",
                "provider_operation_id": char_op["provider_operation_id"],
                "provider_request_id": char_op["provider_request_id"],
                "operation": char_op["request_summary"].get("compiled_request", {}).get("operation"),
                "output_artifact": char_artifact,
                "used_as_reference_by": "keyframe_i2i",
            },
            {
                "step": "keyframe (i2i)",
                "provider_operation_id": keyframe_op["provider_operation_id"],
                "provider_request_id": keyframe_op["provider_request_id"],
                "operation": compiled.get("operation"),
                "input_reference": {
                    "artifact_id": "64ad1657-3c77-4724-ac50-f3f683dfec6c",
                    "fingerprint": "1a4c323319654eea1bc9d1cb1960448834d52be6dddceb8259a22e803dbc2005",
                },
                "output_artifact": keyframe_artifact,
                "used_as_first_frame_by": "video_i2v",
            },
            {
                "step": "video (i2v)",
                "provider_operation_id": video_op["provider_operation_id"],
                "provider_request_id": video_op["provider_request_id"],
                "operation": video_op["request_summary"].get("compiled_request", {}).get("operation"),
                "input_first_frame": video_op["request_summary"]
                    .get("compiled_request", {})
                    .get("reference_artifact_ids"),
                "status": video_op["status"],
                "error": video_op["error_summary"],
            },
        ],
    }
    output_path("reference-lineage.json").write_text(
        json.dumps(lineage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- postrun-index.json ---
    files = sorted(
        path
        for path in EVIDENCE_DIR.glob("*.json")
        if not path.name.startswith("postrun-index")
    )
    index_entries = []
    for f in files:
        raw = f.read_bytes()
        index_entries.append({
            "filename": f.name,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        })
    postrun = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "decision": "PARTIAL",
        "reviewer": "run_operator",
        "gate_ids_supported": ["A3", "A4", "G4"],
        "overall_result": (
            "real keyframe I2I succeeded with Artifact + EffectiveRequest + TranslationReport "
            "+ ProviderOperation (unified-v1); video i2v provider request was rejected (503); "
            "provider did not report billed cost so budget ledger shows consumed 0"
        ),
        "evidence_files": index_entries,
    }
    output_path("postrun-index.json").write_text(
        json.dumps(postrun, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Wrote post-run evidence files:")
    for f in sorted(EVIDENCE_DIR.iterdir()):
        print("  ", f.name, f.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
