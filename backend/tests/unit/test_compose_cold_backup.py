"""A cold window is refused before publishing the receipt if another writer can enter."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "maintenance_cold_backup.py"
spec = importlib.util.spec_from_file_location("maintenance_cold_backup", SCRIPT)
assert spec and spec.loader
cold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cold)


def storage_row():
    return {
        "id": "pg",
        "project": "demo",
        "state": "running",
        "mode": "demo_default",
        "health": [],
        "nets": {"demo_default": {"NetworkID": "net", "IPAddress": "10.10.0.3"}},
        "ports": {"5432/tcp": None},
        "mounts": [
            {"RW": True, "Source": "/volumes/pg/_data", "Destination": "/var/lib/postgresql/data"}
        ],
    }


@pytest.mark.parametrize(
    "kind", ["published", "foreign_network", "foreign_bind", "foreign_namespace", "host"]
)
def test_conflicting_storage_access_is_refused(monkeypatch, kind):
    monkeypatch.setattr(cold, "_docker", lambda *args: "demo")
    pg = storage_row()
    other = {
        "id": "other",
        "project": "unrelated",
        "state": "running",
        "mode": "none",
        "nets": {},
        "mounts": [],
    }
    if kind == "published":
        pg["ports"]["5432/tcp"] = [{"HostPort": "6432"}]
    elif kind == "foreign_network":
        other["nets"] = pg["nets"]
    elif kind == "foreign_bind":
        other["mounts"] = [{"RW": True, "Source": "/volumes"}]
    elif kind == "foreign_namespace":
        other["mode"] = "container:pg"
    else:
        other["mode"] = "host"
    with pytest.raises(RuntimeError):
        cold._scope({"pg": pg, "other": other}, "demo", {"primary": "pg"}, stopped=True)


def _event(kind, action, ident, time, **attrs):
    return {
        "Type": kind,
        "Action": action,
        "timeNano": time,
        "Actor": {"ID": ident, "Attributes": attrs},
    }


@pytest.mark.parametrize(
    "extra",
    [
        _event("container", "exec_start: other-program", "pg", 2),
        _event("network", "connect", "net", 2, container="foreign"),
        _event("volume", "mount", "my-data", 2),
        _event("container", "unpause", "writer", 2, **{"com.docker.compose.project": "demo"}),
    ],
)
def test_transient_writer_cannot_be_hidden_by_final_topology(monkeypatch, extra):
    monkeypatch.setattr(cold, "_containers", lambda: {"pg": storage_row()})
    own = [
        _event("container", "start", "helper", 1, name="capture"),
        _event("container", "die", "helper", 3, name="capture"),
    ]
    cold._check_events(
        own, "capture", {"net"}, {"/volumes/my-data/_data"}, {"primary": "pg"}, "demo"
    )
    with pytest.raises(RuntimeError):
        cold._check_events(
            [own[0], extra, own[1]],
            "capture",
            {"net"},
            {"/volumes/my-data/_data"},
            {"primary": "pg"},
            "demo",
        )
    with pytest.raises(RuntimeError, match="incomplete"):
        cold._check_events(own[1:], "capture", set(), set(), {}, "demo")
