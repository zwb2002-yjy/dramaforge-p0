"""Exact local execution revision and frozen product-policy evidence.

This is an evidence envelope on the existing execution identity, not another
Catalog or Runtime. Unknown historical revisions are blocked; never guessed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


def policy_content_hash(content: dict[str, JsonValue]) -> str:
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


class ExecutionContractSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "1"
    provider_type: str
    protocol_profile: str
    implementation_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    product_policy: dict[str, JsonValue]
    product_policy_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_policy(self) -> ExecutionContractSnapshot:
        if self.schema_version != "1":
            raise ValueError("execution contract schema is unavailable")
        if policy_content_hash(self.product_policy) != self.product_policy_hash:
            raise ValueError("frozen product policy hash mismatch")
        return self


def implementation_fingerprint(provider_type: str, protocol_profile: str) -> str:
    """Pin protocol/handler owner sources, media materialization and locked deps.

    Factory owner modules establish the implementation, without constructing a
    client or reading credentials. Lifecycle/availability/policy decisions are
    not re-evaluated by this fingerprint.
    """
    from app.providers.registry import get_plugin

    plugin = get_plugin(provider_type, protocol_profile)
    root = Path(__file__).resolve().parents[2]
    paths = {
        Path(__file__),
        Path(__file__).with_name("execution_identity.py"),
        Path(__file__).with_name("manifest.py"),
        Path(__file__).with_name("runtime.py"),
        Path(__file__).with_name("image_results.py"),
        Path(__file__).with_name("transport.py"),
        Path(__file__).with_name("transport_registry.py"),
        Path(__file__).with_name("registry.py"),
        Path(__file__).with_name("workspace_credentials.py"),
        Path(__file__).with_name("egress.py"),
        Path(__file__).with_name("http_client.py"),
        Path(__file__).with_name("host_guard.py"),
        root / "app/execution/provider_execution.py",
        root / "app/execution/media_io.py",
        root / "app/config.py",
        root / "app/security/byok_keyring.py",
        root / "app/security/credentials.py",
        root / "uv.lock",
    }
    symbols = []
    for factory in (plugin.runtime_factory, plugin.compiler_factory):
        if factory is None:
            raise ValueError("execution implementation has no registered factory")
        filename = inspect.getsourcefile(factory)
        if filename is None:
            raise ValueError("execution implementation source is unavailable")
        path = Path(filename).resolve()
        if not path.is_relative_to(root):
            raise ValueError("execution factory source is outside the backend package")
        paths.add(path)
        code = getattr(factory, "__code__", None)
        symbols.append(
            {
                "module": getattr(factory, "__module__", None),
                "name": getattr(factory, "__qualname__", None),
                "line": code.co_firstlineno if code is not None else None,
                "bytecode": hashlib.sha256(code.co_code).hexdigest() if code is not None else None,
            }
        )
    hashes = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }
    payload: dict[str, Any] = {
        "provider_type": provider_type,
        "protocol_profile": protocol_profile,
        "settings_prefix": plugin.prefix,
        "credential_provider_key": plugin.credential_provider_key,
        "source_hashes": hashes,
        "factory_symbols": symbols,
        "python": list(sys.version_info[:3]),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def freeze_execution_contract(
    *,
    provider_type: str,
    protocol_profile: str,
    product_policy: dict[str, JsonValue],
) -> ExecutionContractSnapshot:
    return ExecutionContractSnapshot(
        provider_type=provider_type,
        protocol_profile=protocol_profile,
        implementation_fingerprint=implementation_fingerprint(provider_type, protocol_profile),
        product_policy=product_policy,
        product_policy_hash=policy_content_hash(product_policy),
    )


def execution_contract_gaps(contract: ExecutionContractSnapshot | None) -> tuple[str, ...]:
    if contract is None:
        return ("EXECUTION_CONTRACT_MISSING",)
    try:
        # Revalidation catches in-memory mutation of a nested JSON policy too.
        ExecutionContractSnapshot.model_validate(contract.model_dump(mode="json"))
    except ValueError:
        return ("EXECUTION_POLICY_SNAPSHOT_INVALID",)
    try:
        current = implementation_fingerprint(contract.provider_type, contract.protocol_profile)
    except (LookupError, ValueError, OSError, TypeError):
        return ("EXECUTION_HANDLER_UNAVAILABLE",)
    if current != contract.implementation_fingerprint:
        return ("EXECUTION_HANDLER_REVISION_MISMATCH",)
    return ()
