"""Resumable local block receipts for page-ranged PDF extraction.

A block is pure local work: the original bytes plus one page range. The receipt is
written to project-private intermediate storage and bound to the input content hash and
the accepted attempt, so a restart reuses verified blocks and never publishes a partial
"complete" extraction. This is local processing evidence, not a second task state; the
revision attempt and its extraction snapshot remain the authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from app.assets.source_processors import pdf
from app.assets.source_processors.contracts import (
    FragmentDraft,
    ParsedSource,
    ProcessorUse,
    SourceParseError,
)
from app.storage.minio_store import ObjectStore

BLOCK_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BlockReceipt:
    index: int
    page_start: int
    page_end: int
    content_hash: str
    fragments: tuple[FragmentDraft, ...]
    pages_with_text: int
    pages_ocr: int
    omitted_pages: int
    processors: tuple[ProcessorUse, ...]
    page_count: int
    reused: bool = False


def block_key(
    *,
    project_id: UUID,
    content_hash: str,
    revision_id: UUID,
    attempt: int,
    index: int,
) -> str:
    return (
        f"projects/{project_id}/source-blocks/{content_hash}/"
        f"{revision_id}/{attempt}/block-{index:04d}.json"
    )


def _payload(part: pdf.PdfPart) -> dict[str, object]:
    return {
        "schema_version": BLOCK_SCHEMA_VERSION,
        "page_start": part.page_start,
        "page_end": part.page_end,
        "pages_with_text": part.pages_with_text,
        "pages_ocr": part.pages_ocr,
        "omitted_pages": part.omitted_pages,
        "page_count": part.page_count,
        "processors": [use.evidence() for use in part.processors],
        "fragments": [
            {
                "ordinal": fragment.ordinal,
                "locator_kind": fragment.locator_kind,
                "locator": fragment.locator,
                "text": fragment.text,
                "evidence_meta": fragment.evidence_meta,
                "extraction_method": fragment.extraction_method,
                "processor_ref": fragment.processor_ref,
            }
            for fragment in part.fragments
        ],
    }


def receipt_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _int_field(payload: dict[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{key} is not an integer")
    return value


def _object_field(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    if not isinstance(value, dict):
        raise TypeError(f"{key} is not an object")
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _decode(payload: dict[str, object], *, index: int, content_hash: str) -> BlockReceipt | None:
    try:
        raw_fragments = payload["fragments"]
        raw_processors = payload["processors"]
        if not isinstance(raw_fragments, list) or not isinstance(raw_processors, list):
            return None
        fragments = []
        for item in raw_fragments:
            if not isinstance(item, dict):
                return None
            fragments.append(
                FragmentDraft(
                    ordinal=_int_field(item, "ordinal"),
                    locator_kind=str(item["locator_kind"]),
                    locator=_object_field(item, "locator"),
                    text=str(item["text"]),
                    evidence_meta=_object_field(item, "evidence_meta"),
                    extraction_method=str(item["extraction_method"]),
                    processor_ref=str(item["processor_ref"]),
                )
            )
        processors = []
        for item in raw_processors:
            if not isinstance(item, dict):
                return None
            model_sha = item.get("model_sha256")
            processors.append(
                ProcessorUse(
                    ref=str(item["ref"]),
                    engine=str(item["engine"]),
                    version=str(item["version"]),
                    network_mode=str(item.get("network_mode", "local")),
                    model_sha256=model_sha if isinstance(model_sha, str) else None,
                )
            )
        return BlockReceipt(
            index=index,
            page_start=_int_field(payload, "page_start"),
            page_end=_int_field(payload, "page_end"),
            content_hash=content_hash,
            fragments=tuple(fragments),
            pages_with_text=_int_field(payload, "pages_with_text"),
            pages_ocr=_int_field(payload, "pages_ocr"),
            omitted_pages=_int_field(payload, "omitted_pages"),
            processors=tuple(processors),
            page_count=_int_field(payload, "page_count"),
            reused=True,
        )
    except (KeyError, TypeError, ValueError):
        return None


async def load_receipt(store: ObjectStore, key: str, *, index: int) -> BlockReceipt | None:
    try:
        raw = await store.get_bytes(object_key=key)
    except Exception:
        return None
    try:
        envelope = json.loads(raw.decode("utf-8"))
        payload = envelope["payload"]
        stored = str(envelope["content_hash"])
        if not isinstance(payload, dict):
            return None
        if receipt_hash(payload) != stored:
            # A corrupt or foreign block is recomputed, never trusted.
            return None
    except (KeyError, ValueError, UnicodeDecodeError):
        return None
    return _decode(payload, index=index, content_hash=stored)


async def store_receipt(store: ObjectStore, key: str, part: pdf.PdfPart) -> BlockReceipt:
    payload = _payload(part)
    content_hash = receipt_hash(payload)
    body = json.dumps(
        {"content_hash": content_hash, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    await store.put_bytes(
        object_key=key, data=body, mime_type="application/vnd.dramaforge.source-block+json"
    )
    return BlockReceipt(
        index=0,
        page_start=part.page_start,
        page_end=part.page_end,
        content_hash=content_hash,
        fragments=part.fragments,
        pages_with_text=part.pages_with_text,
        pages_ocr=part.pages_ocr,
        omitted_pages=part.omitted_pages,
        processors=part.processors,
        page_count=part.page_count,
    )


async def parse_pdf_with_blocks(
    data: bytes,
    *,
    store: ObjectStore,
    project_id: UUID,
    content_hash: str,
    revision_id: UUID,
    attempt: int,
) -> ParsedSource:
    """Parse every page block, reusing verified receipts, then publish one snapshot."""
    spans = await asyncio.to_thread(pdf.page_spans, data)
    parts: list[pdf.PdfPart] = []
    for index, (start, end) in enumerate(spans):
        key = block_key(
            project_id=project_id,
            content_hash=content_hash,
            revision_id=revision_id,
            attempt=attempt,
            index=index,
        )
        receipt = await load_receipt(store, key, index=index)
        if receipt is not None and receipt.page_start == start and receipt.page_end == end:
            parts.append(
                pdf.PdfPart(
                    page_start=receipt.page_start,
                    page_end=receipt.page_end,
                    fragments=receipt.fragments,
                    pages_with_text=receipt.pages_with_text,
                    pages_ocr=receipt.pages_ocr,
                    omitted_pages=receipt.omitted_pages,
                    processors=receipt.processors,
                    page_count=receipt.page_count,
                )
            )
            continue
        part = await asyncio.to_thread(
            pdf.parse_pdf_part, data, page_start=start, page_end=end
        )
        await store_receipt(store, key, part)
        parts.append(part)
    if not parts:
        raise SourceParseError("source_pdf_invalid")
    return pdf.merge_parts(parts, parts[0].page_count)


__all__ = [
    "BLOCK_SCHEMA_VERSION",
    "BlockReceipt",
    "block_key",
    "load_receipt",
    "parse_pdf_with_blocks",
    "receipt_hash",
    "store_receipt",
]
