"""Connection-time egress enforcement for provider traffic (SSRF closure).

Write-time validation (``app.providers.host_guard``) is the first gate; this
module is the second. Before any TCP connection carrying provider
credentials is opened, the destination host is resolved, every resolved
address is classified by the shared :func:`classify_ip_address` rules, and
the socket is opened against one validated address:

* **DNS rebinding / hostname-to-private redirect**: the socket connects to
  the exact validated IP, never to a re-resolved name. An established
  connection therefore keeps its validated endpoint for its whole
  lifetime; a *new* connection after a DNS change is resolved and
  validated again — including pooled keep-alive reconnects.
* **Mixed A/AAAA records**: one non-authorizable address in the resolution
  set fails the whole connection (fail closed).
* **Existing connections**: connections saved under earlier policy are
  re-validated here on every new socket, so a stored base_url cannot
  bypass the current rules at runtime.

Violations raise :class:`httpx.ConnectError` (a ``TransportError``) through
the existing provider error handling, without any credential bytes leaving
the process. No request is retried here.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable, Sequence
from typing import Protocol

import httpcore
import httpx
from httpcore._backends.base import (
    SOCKET_OPTION,
    AsyncNetworkBackend,
    AsyncNetworkStream,
)

from app.config import Settings, get_settings
from app.providers.host_guard import classify_ip_address, validate_provider_base_url
from app.shared.errors import ValidationAppError

_EGRESS_BLOCKED = "PROVIDER_EGRESS_BLOCKED_TARGET"
_EGRESS_PRIVATE = "PROVIDER_EGRESS_PRIVATE_NOT_AUTHORIZED"
_EGRESS_SHARED = "PROVIDER_EGRESS_SHARED_NOT_AUTHORIZED"
_EGRESS_UNIX = "PROVIDER_EGRESS_UNIX_SOCKET_BLOCKED"
_EGRESS_UNRESOLVABLE = "PROVIDER_EGRESS_UNRESOLVABLE"


class AddressResolver(Protocol):
    """Async ``(host, port) -> resolved address list`` (injectable in tests)."""

    async def __call__(self, host: str, port: int) -> list[str]: ...


async def _resolve_addresses(host: str, port: int) -> list[str]:
    if _is_ip_literal(host):
        return [host]
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    except OSError as exc:
        raise httpx.ConnectError(f"{_EGRESS_UNRESOLVABLE}: {host!r}") from exc
    addresses = {str(info[4][0]) for info in infos}
    if not addresses:
        raise httpx.ConnectError(f"{_EGRESS_UNRESOLVABLE}: {host!r}")
    return sorted(addresses)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _normalize_host(host: str) -> str:
    return host.strip("[]").rstrip(".").lower()


class ProviderEgressPolicy:
    """Immutable connection-time destination policy (fail closed)."""

    __slots__ = ("allow_private", "trusted_networks")

    def __init__(
        self,
        *,
        allow_private: bool = False,
        trusted_networks: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (),
    ) -> None:
        self.allow_private = allow_private
        self.trusted_networks = trusted_networks

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ProviderEgressPolicy:
        cfg = settings or get_settings()
        return cls(
            allow_private=cfg.provider_base_url_allow_private,
            trusted_networks=cfg.provider_trusted_network_objects(),
        )

    def check_address(self, address: str) -> None:
        """Raise :class:`httpx.ConnectError` when credentials may not reach ``address``."""

        category = classify_ip_address(address)
        if category == "hard_blocked":
            raise httpx.ConnectError(f"{_EGRESS_BLOCKED}: {address}")
        if category == "shared_non_global":
            raise httpx.ConnectError(f"{_EGRESS_SHARED}: {address}")
        if self.trusted_networks:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                ip = None
            if ip is not None and any(ip in network for network in self.trusted_networks):
                return
        if category == "public":
            return
        if category == "private_deployment":
            if self.allow_private:
                return
            raise httpx.ConnectError(f"{_EGRESS_PRIVATE}: {address}")
        raise httpx.ConnectError(f"{_EGRESS_SHARED}: {address}")

    def validate_addresses(self, addresses: Sequence[str]) -> tuple[str, ...]:
        """Validate the whole resolution set before trying any socket."""

        if not addresses:
            raise httpx.ConnectError(_EGRESS_UNRESOLVABLE)
        for address in addresses:
            self.check_address(address)
        return tuple(sorted(set(addresses)))


class GuardedProviderNetworkBackend(AsyncNetworkBackend):
    """Resolve, classify, then open the socket against a validated address."""

    def __init__(
        self,
        *,
        policy: ProviderEgressPolicy | None = None,
        resolver: AddressResolver | None = None,
        inner: AsyncNetworkBackend | None = None,
    ) -> None:
        from httpcore._backends.auto import AutoBackend

        self._policy = policy or ProviderEgressPolicy.from_settings()
        self._resolver = resolver or _resolve_addresses
        self._backend = inner or AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        try:
            # DNS and all TCP candidates share the caller's connect deadline.
            async with asyncio.timeout(timeout) as deadline:
                target = _normalize_host(host)
                if _is_ip_literal(target):
                    addresses: list[str] = [target]
                else:
                    try:
                        addresses = await self._resolver(target, port)
                    except OSError as exc:
                        raise httpx.ConnectError(f"{_EGRESS_UNRESOLVABLE}: {target!r}") from exc
                validated = self._policy.validate_addresses(addresses)
                options = list(socket_options) if socket_options is not None else None
                last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
                for pinned in validated:
                    expires_at = deadline.when()
                    remaining = (
                        max(0.0, expires_at - asyncio.get_running_loop().time())
                        if expires_at is not None
                        else None
                    )
                    try:
                        return await self._backend.connect_tcp(
                            pinned,
                            port,
                            timeout=remaining,
                            local_address=local_address,
                            socket_options=options,
                        )
                    except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                        # No stream has been returned and no HTTP bytes sent.
                        # Trying another validated address is connection setup,
                        # never a retry of a possibly billed Provider request.
                        last_error = exc
                assert last_error is not None  # Empty answers fail validation.
                raise last_error
        except TimeoutError as exc:
            raise httpx.ConnectTimeout("provider DNS/TCP connection timed out") from exc

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        raise httpx.ConnectError(
            f"{_EGRESS_UNIX}: provider traffic must use validated TCP destinations"
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class GuardedProviderTransport(httpx.AsyncHTTPTransport):
    """Recheck request URLs, including old stored origins, before pool access."""

    def __init__(self, *, settings: Settings, max_connections: int = 16) -> None:
        super().__init__(trust_env=False, limits=httpx.Limits(max_connections=max_connections))
        self._settings = settings
        # HTTPX has no network_backend argument; use the same seam as media_io.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=self._pool._ssl_context,
            max_connections=max_connections,
            max_keepalive_connections=min(8, max_connections),
            network_backend=GuardedProviderNetworkBackend(
                policy=ProviderEgressPolicy.from_settings(settings)
            ),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            validate_provider_base_url(str(request.url), settings=self._settings)
        except ValidationAppError as exc:
            raise httpx.ConnectError(
                str(exc.details.get("code", _EGRESS_BLOCKED)), request=request
            ) from exc
        return await super().handle_async_request(request)

    @property
    def settings(self) -> Settings:
        return self._settings


def guarded_provider_transport(
    *,
    settings: Settings | None = None,
    max_connections: int = 16,
) -> httpx.AsyncHTTPTransport:
    """Build an HTTP transport whose every connection is policy-guarded.

    TLS hostname/SNI verification is unchanged: httpcore wraps the returned
    stream with the request's origin hostname, while the socket itself is
    opened against the validated address (the same pinning pattern as
    ``app.execution.media_io._PinnedNetworkBackend`` for provider media
    downloads). Each caller owns its transport: exiting an AsyncClient must
    not close a pool used by an unrelated submission, probe or event loop.
    """

    return GuardedProviderTransport(
        settings=settings or get_settings(), max_connections=max_connections
    )


__all__ = [
    "AddressResolver",
    "GuardedProviderNetworkBackend",
    "ProviderEgressPolicy",
    "guarded_provider_transport",
]
