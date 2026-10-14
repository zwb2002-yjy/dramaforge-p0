"""Offline source registration, immutable snapshot/check append, and evidence lint.

Never calls a Provider, fetches a URL, edits a Manifest or publishes an Active model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.providers.source_evidence import (
    SourceCheck,
    SourceRecord,
    SourceSnapshot,
    load_source_evidence,
)

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "backend/app/providers/model_sources"


@contextmanager
def metadata_writer(root: Path) -> Iterator[None]:
    """Refuse overlapping writers; never clear another process's lock."""
    lock = root / ".source-metadata.lock"
    with lock.open("x", encoding="utf-8") as file:
        file.write("offline source metadata writer\n")
    try:
        yield
    finally:
        lock.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("lint")
    for command in ("register", "snapshot", "check"):
        item = commands.add_parser(command)
        item.add_argument("--record-json", type=Path, required=True)
        if command == "snapshot":
            item.add_argument("--body", type=Path)
    args = parser.parse_args()
    if args.command != "lint":
        with metadata_writer(args.root):
            return append_record(args)
    store = load_source_evidence(args.root)
    if args.command == "lint":
        print(
            json.dumps(
                {
                    "sources": len(store.sources),
                    "unique_urls": len({source.url for source in store.sources}),
                    "snapshots": len(store.snapshots),
                    "checks": len(store.checks),
                    "reviewed_snapshots": sum(
                        snapshot.review_status == "reviewed" for snapshot in store.snapshots
                    ),
                    "unavailable_snapshots": sum(
                        snapshot.capture_status == "unavailable" for snapshot in store.snapshots
                    ),
                    "capabilities": "not_defined_by_source_metadata",
                    "provider_calls": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0


def append_record(args: argparse.Namespace) -> int:
    store = load_source_evidence(args.root)
    record = json.loads(args.record_json.read_text(encoding="utf-8"))
    if args.command == "snapshot":
        snapshot = SourceSnapshot.model_validate(record)
        if snapshot.capture_status == "captured":
            if (
                args.body is None
                or hashlib.sha256(args.body.read_bytes()).hexdigest() != snapshot.content_sha256
            ):
                raise ValueError("captured snapshot requires the actual hash-matching source body")
        elif args.body is not None:
            raise ValueError("unavailable snapshot cannot claim a captured source body")
        updated = store.append_snapshot(snapshot)
        filename, key = "source_snapshots.json", "snapshots"
    elif args.command == "check":
        updated = store.append_check(SourceCheck.model_validate(record))
        filename, key = "source_checks.json", "checks"
    else:
        updated = store.append_source(SourceRecord.model_validate(record))
        filename, key = "source_registry.json", "sources"
    target = args.root / filename
    if updated is store:
        print(json.dumps({"file": str(target), "changed": False, "provider_calls": 0}))
        return 0
    # Preserve prior records exactly, including original timestamp precision.
    payload = json.loads(target.read_text(encoding="utf-8"))
    identity_key = {
        "sources": "source_id",
        "snapshots": "source_snapshot_id",
        "checks": "check_id",
    }[key]
    new_record = next(
        item
        for item in updated.model_dump(mode="json")[key]
        if item[identity_key] == record[identity_key]
    )
    for index, previous in enumerate(payload[key]):
        if previous[identity_key] == new_record[identity_key]:
            payload[key][index] = new_record
            break
    else:
        payload[key].append(new_record)
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(target)
    print(json.dumps({"file": str(target), "manifest_modified": False, "provider_calls": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
