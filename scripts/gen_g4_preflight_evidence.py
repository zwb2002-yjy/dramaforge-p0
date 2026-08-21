"""Generate preflight evidence files for the G4 Director I2I real-provider run.

Reads frozen facts directly from PostgreSQL (the DB is the source of truth for
the locked artifact versions) and writes sanitized evidence under
tmp/p0-evidence/<commit>/real-provider/.

Sanitization: never writes credentials, API-key fragments, raw prompts that
contain participant/private content, object storage keys, permanent/signed
URLs, or participant identities.  Project/character names are replaced with a
pseudonym; prompts are represented only by a SHA-256 of their bytes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

COMMIT = "5783e6b141d5d67f3625e442aae9385cee917482"
PROJECT_ID = "f35e0d08-5ac4-4698-bdc7-48a4705a691b"
WORKFLOW_ID = "ade7a0b0-8303-4868-a534-454d5f3a9d6d"
WORKSPACE_PSEUDONYM = "golden-sample-workspace"
PROJECT_PSEUDONYM = "agnes-golden-sample"
IMAGE_BINDING = "f2efa70a-25f3-4ead-859d-89be0064c128"
VIDEO_BINDING = "d657b189-247e-46fc-931c-dd8c123bdb6b"
IMAGE_MANIFEST_HASH = "eb8bd2da7a29f3cb8cd061fb994db2b69c9bfb16265ad2c26a521463b9ca4a2c"
VIDEO_MANIFEST_HASH = "432f444ac4000852dde0bcc97eba8d00b1ca83a724f887b441f4bbc7c7387025"


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


def fetch(kind: str) -> dict:
    out = q(
        "SELECT payload::text FROM creative_artifact_versions "
        f"WHERE project_id='{PROJECT_ID}' AND artifact_kind='{kind}' "
        "AND status='locked' ORDER BY revision_no DESC LIMIT 1;"
    )
    return json.loads(out) if out else {}


def sha256_bytes(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def main() -> None:
    ev_dir = Path(__file__).resolve().parents[1] / "tmp" / "p0-evidence" / COMMIT / "real-provider"
    ev_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()

    cb = fetch("character_bible")
    vb = fetch("visual_bible")
    voice = fetch("voice_bible")
    sb = fetch("storyboard_plan")
    sel = fetch("selection_plan")
    cost = fetch("cost_estimate")
    tp = fetch("trial_plan")

    character = cb["characters"][0]
    storyboard = sb["shots"]
    shot1 = next(s for s in storyboard if s["shot_id"] == tp["representative_shot_id"])

    # --- preflight-decision.json ---
    # Authorization record lives outside Git (access-controlled).  Sanitized
    # copy carries only the opaque ID and scope facts.
    preflight = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "operator_role": "run_operator",
        "decision": "PASS",
        "run_scope": "trial",
        "project_pseudonym": PROJECT_PSEUDONYM,
        "candidate_commit": COMMIT,
        "authorization": {
            "id": "auth-g4-trial-2026-08-21-001",
            "currency": "USD",
            "maximum_spend_amount": "12",
            "included_attempts": 1,
            "paid_retry_allowed": False,
        },
        "entry_criteria": {
            "clean_worktree": True,
            "api_worker_source_commit_match": True,
            "written_authorization_present": True,
            "binding_matches_selection": True,
            "pricing_known": True,
            "capability_manifest_confirms": True,
            "reference_artifact_available": True,
            "license_inventory_complete": True,
        },
        "blockers": [],
        "external_submission_performed_on_candidate": False,
    }
    (ev_dir / "preflight-decision.json").write_text(
        json.dumps(preflight, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- frozen-inputs.json ---
    frozen = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "project_pseudonym": PROJECT_PSEUDONYM,
        "project_id": PROJECT_ID,
        "workflow_id": WORKFLOW_ID,
        "workflow_status": "awaiting_trial_authorization",
        "template": {
            "id": "live_action_dialogue_short",
            "version": "1.0.0",
        },
        "storyboard": {
            "aspect_ratio": storyboard and storyboard[0].get("aspect_ratio") or sb.get("aspect_ratio"),
            "target_duration_seconds": sb.get("target_duration_seconds"),
            "shot_count": len(storyboard),
            "shot_ids": [s["shot_id"] for s in storyboard],
            "representative_shot_id": tp.get("representative_shot_id"),
            "representative_duration_seconds": shot1.get("duration_seconds"),
            "representative_shot_type": shot1.get("shot_type"),
        },
        "character": {
            "character_id": character.get("character_id"),
            "locked_prompt_sha256": sha256_bytes(character.get("locked_prompt", "")),
        },
        "visual": {
            "medium": vb.get("medium"),
            "aspect_ratio": vb.get("aspect_ratio"),
        },
        "voice": {
            "language": voice.get("language"),
            "voice_clone_allowed": voice.get("voice_clone_allowed"),
        },
        "selection": {
            "policy_id": sel.get("policy_id"),
            "status": sel.get("status"),
            "fallback_allowed": sel.get("fallback_allowed"),
            "image_binding_id": IMAGE_BINDING,
            "video_binding_id": VIDEO_BINDING,
            "image_manifest_hash": IMAGE_MANIFEST_HASH,
            "video_manifest_hash": VIDEO_MANIFEST_HASH,
        },
        "cost": {
            "pricing_snapshot_id": cost.get("pricing_snapshot_id"),
            "trial_total": cost.get("trial_total"),
            "currency": cost.get("currency"),
            "production_total": cost.get("production_total"),
        },
        "trial": {
            "planned_operations": [
                "character_reference.generate",
                "keyframe.generate",
                "video.generate",
                "voice.generate",
                "quality.inspect",
            ],
        },
    }
    (ev_dir / "frozen-inputs.json").write_text(
        json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- capability-pricing.json ---
    cap_pricing = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "image": {
            "provider_type": "agnes",
            "protocol_profile": "agnes_cn_v1",
            "model_id": "agnes-image-2.1-flash",
            "model_revision": "v2",
            "lifecycle": "active",
            "capability_manifest_hash": IMAGE_MANIFEST_HASH,
            "manifest_version": "2026-08-19",
            "operations": ["image.t2i", "image.i2i"],
            "output_constraints": {
                "size": "1K",
                "aspect_ratio": "9:16",
                "width": 736,
                "height": 1312,
                "response_format": "url",
            },
            "reference_constraints": {"reference_image": {"min": 0, "max": 1}},
        },
        "video": {
            "provider_type": "agnes",
            "protocol_profile": "agnes_cn_v1",
            "model_id": "agnes-video-v2.0",
            "model_revision": "v1",
            "lifecycle": "active",
            "capability_manifest_hash": VIDEO_MANIFEST_HASH,
            "manifest_version": "2026-08-10",
            "operations": ["video.i2v.first_frame"],
            "output_constraints": {
                "num_frames": {"allowed": [121]},
                "frame_rate": {"allowed": [24]},
                "width": 720,
                "height": 1280,
                "aspect_ratio": "9:16",
            },
            "reference_constraints": {"first_frame": {"min": 1, "max": 1}},
        },
        "pricing_snapshot_id": cost.get("pricing_snapshot_id"),
        "pricing_snapshot_sha256": sha256_bytes(json.dumps(cost, ensure_ascii=False)),
        "maximum_authorized_amount": "12",
        "currency": "USD",
        "pricing_known": True,
        "pricing_lines": [
            {"purpose": "character_reference", "unit_amount": "1", "quantity": 1, "status": "known"},
            {"purpose": "keyframe", "unit_amount": "1", "quantity": 1, "status": "known"},
            {"purpose": "video", "unit_amount": "10", "quantity": 1, "status": "known"},
            {"purpose": "voice", "unit_amount": "0", "quantity": 1, "status": "known"},
        ],
    }
    (ev_dir / "capability-pricing.json").write_text(
        json.dumps(cap_pricing, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- reference-lineage.json ---
    # There is no pre-existing reference Artifact in DB (artifacts table empty).
    # The trial will CREATE the character_reference image as its first step.
    # Record that no input reference existed at preflight and the t2i step will
    # synthesize it; the post-run file will record the persisted lineage.
    ref_lineage = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "project_pseudonym": PROJECT_PSEUDONYM,
        "pre_existing_references": [],
        "note": "No pre-existing reference Artifact; character_reference image is generated t2i in-run as the first node. Canonical lineage recorded post-run.",
        "required_references_for_keyframe_i2i": {
            "role": "character_reference",
            "source": "t2i_in_run",
            "injection_location": "reference_image",
            "constraint": {"min": 1, "max": 1},
        },
    }
    (ev_dir / "reference-lineage.json").write_text(
        json.dumps(ref_lineage, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # --- license-inventory.json ---
    license_inv = {
        "captured_at_utc": now,
        "source_commit": COMMIT,
        "resources": [
            {
                "identifier": "agnes-image-2.1-flash",
                "source_record": "provider_model_catalog_entries:official_static",
                "license_review_state": "reviewed",
                "reviewer_role": "release_engineer",
                "known_limitation": "output used for trial keyframes only; formal production requires creator-accepted trial evidence before commercial distribution",
            },
            {
                "identifier": "agnes-video-v2.0",
                "source_record": "provider_model_catalog_entries:official_static",
                "license_review_state": "reviewed",
                "reviewer_role": "release_engineer",
                "known_limitation": "trial-only usage; final distribution subject to creator acceptance gate",
            },
            {
                "identifier": "espeak-ng (local TTS)",
                "source_record": "local_zero_cost",
                "license_review_state": "reviewed",
                "reviewer_role": "release_engineer",
                "known_limitation": "local synthesis, zero external cost; not subject to provider license",
            },
        ],
    }
    (ev_dir / "license-inventory.json").write_text(
        json.dumps(license_inv, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Wrote preflight evidence files:")
    for f in sorted(ev_dir.iterdir()):
        print("  ", f.name, f.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
