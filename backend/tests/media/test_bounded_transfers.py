"""Real pinned HTTPS + MinIO SDK transfer RSS proof, isolated quality service only.

The server runs in a separate process. No transport is injected, TLS verification
remains enabled, and only this container's loopback gains a public test address.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import ipaddress
import json
import multiprocessing
import os
import socket
import socketserver
import ssl
import struct
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import get_settings
from app.execution.media_io import _download_provider_media
from app.storage.materialized import materialize_stream
from app.storage.minio_store import MinioObjectStore
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ADDRESS = "93.184.216.34"
CHUNK = b"\0" * (64 * 1024)
HEADER = b"\x00\x00\x00\x18ftypmp42"


def _serve(cert: str, key: str, ready) -> None:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            size = int(self.path.rsplit("/", 1)[-1])
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            self.wfile.write(HEADER)
            remaining = size - len(HEADER)
            try:
                while remaining:
                    count = min(len(CHUNK), remaining)
                    self.wfile.write(CHUNK[:count])
                    remaining -= count
            except (ConnectionError, ssl.SSLError):
                pass

        def log_message(self, *_args):
            pass

    class Server(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer's default reverse DNS lookup is irrelevant to this
            # isolated IP fixture and can wait for an external PTR timeout.
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = "isolated-media", 9443

    server = Server((ADDRESS, 9443), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    ready.set()
    server.serve_forever()


def _rss() -> int:
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * 1024
    raise AssertionError("Linux RSS measurement unavailable")


@pytest.fixture
def https_media_server(tmp_path, monkeypatch):
    assert os.environ.get("MEDIA_RESOURCE_REQUIRED") == "1", "Use media-resource-quality"
    # SIOCSIFADDR: alias is confined to the disposable quality network namespace.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as interface:
        request = struct.pack(
            "16sH2s4s8s",
            b"lo:dfmedia",
            socket.AF_INET,
            b"\0\0",
            socket.inet_aton(ADDRESS),
            b"\0" * 8,
        )
        fcntl.ioctl(interface, 0x8916, request)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "isolated-media-quality")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ADDRESS))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "ca.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    original_context = ssl.create_default_context

    def trusted_context(*args, **kwargs):
        context = original_context(*args, **kwargs)
        context.load_verify_locations(cafile=str(cert_path))
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        return context

    monkeypatch.setattr(ssl, "create_default_context", trusted_context)
    # Poison proxy settings: production trust_env=False must still use direct TLS.
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    server = context.Process(target=_serve, args=(str(cert_path), str(key_path), ready))
    server.start()
    try:
        assert ready.wait(10), "HTTPS mock failed to bind in the isolated container"
        yield
    finally:
        server.terminate()
        server.join(10)
        assert not server.is_alive()


@pytest.mark.parametrize("concurrency", [1, 4])
async def test_real_https_and_minio_256mib_stay_bounded(
    https_media_server,
    tmp_path,
    record_property,
    concurrency,
):
    store = MinioObjectStore(get_settings())
    prefix = f"quality-media/{uuid4().hex}"
    size = 256 * 1024 * 1024
    digest = hashlib.sha256(HEADER)
    remaining = size - len(HEADER)
    while remaining:
        count = min(len(CHUNK), remaining)
        digest.update(CHUNK[:count])
        remaining -= count
    expected_hash = digest.hexdigest()
    warm = await _download_provider_media(
        kind="video",
        artifact_uri=f"https://{ADDRESS}:9443/media/{1024 * 1024}",
        destination=tmp_path / "warm.mp4",
    )
    sentinel = await store.put_file(
        object_key=f"{prefix}/sentinel", path=warm.path, mime_type="video/mp4"
    )
    keys = [f"{prefix}/video-{index}" for index in range(concurrency)]
    evidence = []

    async def measure(stage, operation):
        baseline = _rss()
        peak = [baseline]
        stop = threading.Event()

        def sample():
            while not stop.wait(0.005):
                peak[0] = max(peak[0], _rss())

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.monotonic()
        try:
            result = await operation()
            peak[0] = max(peak[0], _rss())
        finally:
            stop.set()
            sampler.join(5)
        evidence.append(
            {
                "stage": stage,
                "warm_rss": baseline,
                "peak_rss": peak[0],
                "rss_delta": peak[0] - baseline,
                "seconds": round(time.monotonic() - started, 3),
            }
        )
        assert peak[0] - baseline <= 128 * 1024 * 1024, evidence
        return result

    try:

        async def download():
            return await asyncio.gather(
                *(
                    _download_provider_media(
                        kind="video",
                        artifact_uri=f"https://{ADDRESS}:9443/media/{size}",
                        destination=tmp_path / f"video-{index}.mp4",
                    )
                    for index in range(concurrency)
                )
            )

        files = await measure("https_download", download)
        assert all(item.byte_size == size and item.content_hash == expected_hash for item in files)

        async def upload():
            return await asyncio.gather(
                *(
                    store.put_file(object_key=key, path=media.path, mime_type="video/mp4")
                    for key, media in zip(keys, files, strict=True)
                )
            )

        uploaded = await measure("minio_upload", upload)
        assert all(
            item.byte_size == size and item.content_hash == expected_hash for item in uploaded
        )

        async def verify():
            for index, key in enumerate(keys):
                assert await store.get_size(object_key=key) == size
                await materialize_stream(
                    store.iter_bytes(object_key=key),
                    destination=tmp_path / f"verified-{index}.mp4",
                    max_bytes=size,
                    expected_size=size,
                    expected_hash=expected_hash,
                )

        await measure("minio_stream_read", verify)
        assert await store.get_size(object_key=sentinel.object_key) == warm.byte_size
        report = {
            "concurrency": concurrency,
            "bytes_per_operation": size,
            "sample_interval_ms": 5,
            "provider_create_count": 0,
            "stages": evidence,
            "cpu_count": os.cpu_count(),
            "platform": os.uname().release,
            "cgroup_memory": Path("/sys/fs/cgroup/memory.max").read_text().strip(),
            "cgroup_cpu": Path("/sys/fs/cgroup/cpu.max").read_text().strip(),
        }
        record_property("media_transfer_rss", json.dumps(report, sort_keys=True))
        print(json.dumps(report, sort_keys=True))
    finally:
        for key in [*keys, sentinel.object_key]:
            await store.delete_bytes(object_key=key)
