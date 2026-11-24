"""Host-side cold backup for one local Docker Compose deployment."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4


def _docker(*args: str, data: str | None = None) -> str:
    result = subprocess.run(
        ["docker", *args],
        input=data,
        stdin=subprocess.DEVNULL if data is None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        # Docker and Compose diagnostics can echo sensitive environment substitutions.
        if data is not None:
            for line in reversed(result.stderr.splitlines()):
                if match := re.fullmatch(r'\s*\{"error":\s*"([A-Za-z0-9_]{1,100})"\}\s*', line):
                    raise RuntimeError(f"capture refused: {match.group(1)}")
        raise RuntimeError(f"Docker {args[0]} failed ({result.returncode})")
    return result.stdout.strip()


def _containers() -> dict[str, dict[str, Any]]:
    ids = _docker("ps", "-aq", "--no-trunc").split()
    if not ids:
        return {}
    # Do not read container environments, arguments or secret values.
    template = "\t".join(
        (
            "{{.Id}}",
            "{{.Name}}",
            "{{.Image}}",
            '{{index .Config.Labels "com.docker.compose.project"}}',
            '{{index .Config.Labels "com.docker.compose.service"}}',
            "{{.State.Status}}",
            "{{.HostConfig.NetworkMode}}",
            "{{json .Mounts}}",
            "{{json .NetworkSettings.Networks}}",
            "{{json .NetworkSettings.Ports}}",
            "{{.State.ExitCode}}",
            '{{json (index .Config "Healthcheck")}}',
            '{{with index .State "Health"}}{{index . "Status"}}{{else}}none{{end}}',
        )
    )
    # Unrelated short-lived jobs may disappear between ps and inspect. Re-enumerate
    # rather than treating a partial inventory as proof of isolation.
    for attempt in range(3):
        try:
            rows = _docker("inspect", "--format", template, *ids)
            break
        except RuntimeError:
            refreshed = _docker("ps", "-aq", "--no-trunc").split()
            if attempt == 2 or set(refreshed) == set(ids):
                raise
            ids = refreshed
    else:
        raise RuntimeError("no stable container inventory available")
    result = {}
    for row in rows.splitlines():
        (
            ident,
            name,
            image,
            project,
            service,
            state,
            mode,
            mounts,
            nets,
            ports,
            code,
            health,
            readiness,
        ) = row.split("\t")
        result[ident] = dict(
            id=ident,
            name=name.lstrip("/"),
            image=image,
            project=project,
            service=service,
            state=state,
            mode=mode,
            mounts=json.loads(mounts),
            nets=json.loads(nets) or {},
            ports=json.loads(ports) or {},
            code=int(code),
            health=(json.loads(health) or {}).get("Test", []),
            health_config=json.loads(health) or {},
            readiness=readiness,
        )
    return result


def _overlap(a: str, b: str) -> bool:
    left, right = PurePosixPath(a), PurePosixPath(b)
    return left == right or left in right.parents or right in left.parents


def _scope(
    rows: dict[str, dict[str, Any]], project: str, storage: dict[str, str], *, stopped: bool
) -> tuple[dict[str, list[str]], set[str], set[str]]:
    nets = set()
    mounts = set()
    ips = {}
    for role, ident in storage.items():
        row = rows.get(ident)
        if not row or row["project"] != project or row["state"] != "running" or not row["nets"]:
            raise RuntimeError("storage identity or readiness changed")
        if any(row["ports"].values()) or row["mode"] in {"host", "none"}:
            raise RuntimeError("storage is not confined to unpublished project networks")
        addresses = []
        for net, values in row["nets"].items():
            if (
                _docker(
                    "network",
                    "inspect",
                    "--format",
                    '{{index .Labels "com.docker.compose.project"}}',
                    net,
                )
                != project
            ):
                raise RuntimeError("storage network is shared or unmanaged")
            nets.add(values["NetworkID"])
            addresses.extend(
                ip for ip in (values.get("IPAddress"), values.get("GlobalIPv6Address")) if ip
            )
        if not addresses:
            raise RuntimeError("storage has no verifiable local address")
        ips[role] = addresses
        data_path = "/data" if role == "minio" else "/var/lib/postgresql/data"
        source = [m["Source"] for m in row["mounts"] if m["Destination"] == data_path]
        if len(source) != 1:
            raise RuntimeError("storage data mount cannot be identified")
        mounts.add(source[0])
        mounts.update(m["Source"] for m in row["mounts"] if m["RW"])
    storage_ids = set(storage.values())
    for row in rows.values():
        if row["id"] in storage_ids or row["state"] not in {"running", "paused", "restarting"}:
            continue
        if row["project"] == project and not stopped:
            continue
        network_access = any(v["NetworkID"] in nets for v in row["nets"].values())
        # Includes containers sharing a peer's network namespace.
        owner = (
            rows.get(row["mode"].removeprefix("container:"))
            if row["mode"].startswith("container:")
            else None
        )
        if owner:
            network_access |= any(v["NetworkID"] in nets for v in owner["nets"].values())
        volume_access = any(
            m["RW"] and any(_overlap(m["Source"], src) for src in mounts) for m in row["mounts"]
        )
        if (
            row["mode"] == "host"
            or network_access
            or volume_access
            or (stopped and row["project"] == project)
        ):
            raise RuntimeError("an additional active container can write the protected resources")
    return ips, nets, mounts


def _service(rows: dict[str, dict[str, Any]], project: str, service: str) -> dict[str, Any]:
    matched = [
        row for row in rows.values() if row["project"] == project and row["service"] == service
    ]
    if len(matched) != 1:
        raise RuntimeError(f"expected one project container for {service}")
    return matched[0]


def _resume(rows: dict[str, dict[str, Any]], stopped: list[str]) -> None:
    failed = []
    waits = {}
    for ident in reversed(stopped):
        try:
            _docker("start", ident)
            check = rows[ident]["health_config"]
            budget = (
                check.get("StartPeriod", 0)
                + (check.get("Interval") or 30_000_000_000) * (1 + (check.get("Retries") or 3))
                + (check.get("Timeout") or 30_000_000_000) * (check.get("Retries") or 3)
            ) / 1e9
            waits[ident] = time.monotonic() + budget + 5
        except RuntimeError:
            failed.append(rows[ident]["service"])
    while waits:
        for ident, deadline in list(waits.items()):
            state = _docker(
                "inspect",
                "--format",
                '{{.State.Status}} {{with index .State "Health"}}'
                '{{index . "Status"}}{{else}}none{{end}}',
                ident,
            )
            if state.startswith("running ") and (
                rows[ident]["readiness"] != "healthy" or state == "running healthy"
            ):
                del waits[ident]
            elif (
                state.startswith(("exited", "dead"))
                or state == "running unhealthy"
                or time.monotonic() > deadline
            ):
                failed.append(rows[ident]["service"])
                del waits[ident]
        if waits:
            time.sleep(1)
    if failed:
        raise RuntimeError("unable to resume original service readiness: " + ",".join(failed))


def _configured_source(
    row: dict[str, Any], setting: str, *, object_store: bool = False
) -> dict[str, str]:
    # Only project deployment metadata leaves this process; passwords never enter reports,
    # capture arguments or the worker's stdin. The configuration must be complete.
    template = (
        '{{range .Config.Env}}{{if eq (index (split . "=") 0) "'
        + setting
        + '"}}{{println .}}{{end}}{{end}}'
    )
    raw = _docker("inspect", "--format", template, row["id"])
    url = urlsplit(raw.removeprefix(setting + "="))
    if not url.hostname:
        raise RuntimeError(f"deployed {setting} is missing")
    if object_store:
        return {
            "host": url.hostname,
            "port": str(url.port or (443 if url.scheme == "https" else 80)),
        }
    if url.scheme not in {"postgresql", "postgres", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise RuntimeError("deployed database protocol is unsupported")
    return {
        "host": url.hostname,
        "port": str(url.port or 5432),
        "database": unquote(url.path.lstrip("/")),
    }


def _check_events(
    events: list[dict[str, Any]],
    worker: str,
    nets: set[str],
    mounts: set[str],
    storage: dict[str, str],
    project: str,
) -> None:
    # Docker only retains a bounded history. Missing our own start/die witnesses means
    # the interval cannot be proved, even if its final topology looks identical.
    own = [
        e
        for e in events
        if e.get("Type") == "container"
        and e.get("Actor", {}).get("Attributes", {}).get("name") == worker
    ]
    started = [e for e in own if e["Action"] == "start"]
    finished = [e for e in own if e["Action"] == "die"]
    if len(started) != 1 or len(finished) != 1:
        raise RuntimeError("incomplete Docker event window")
    helper_id = started[0]["Actor"]["ID"]
    rows = _containers()
    for event in events:
        actor = event["Actor"]
        ident = actor["ID"]
        attrs = actor.get("Attributes", {})
        action = event["Action"]
        if ident == helper_id or attrs.get("container") == helper_id:
            continue
        if ident in storage.values() and action.startswith("exec_start"):
            health = rows[ident]["health"]
            permitted = (
                [" ".join(health[1:])]
                if health[:1] == ["CMD"]
                else ["/bin/sh -c " + " ".join(health[1:]), "sh -c " + " ".join(health[1:])]
            )
            if not any(action == "exec_start: " + cmd for cmd in permitted):
                raise RuntimeError("additional storage exec discovered during capture")
        if (
            event["Type"] == "network"
            and ident in nets
            and action in {"connect", "disconnect", "destroy"}
        ):
            raise RuntimeError("protected network membership changed during capture")
        if (
            event["Type"] == "volume"
            and action in {"mount", "unmount", "destroy"}
            and any(ident in PurePosixPath(path).parts for path in mounts)
        ):
            raise RuntimeError("protected volume membership changed during capture")
        if event["Type"] == "container" and (
            (
                ident in storage.values()
                and action in {"die", "stop", "restart", "pause", "destroy", "kill"}
            )
            or (
                attrs.get("com.docker.compose.project") == project
                and action in {"start", "unpause", "restart"}
            )
        ):
            raise RuntimeError("a protected writer or storage process changed state")
        if (
            event["Type"] == "container"
            and action in {"start", "unpause", "restart"}
            and ident not in storage.values()
        ):
            # Direct bind-mount access or shared networking may have no network-connect event.
            row = rows.get(ident)
            if (
                not row
                or row["mode"].startswith("container:")
                or any(
                    m["RW"] and any(_overlap(m["Source"], src) for src in mounts)
                    for m in row["mounts"]
                )
            ):
                raise RuntimeError("concurrent container access could not be excluded")


@contextmanager
def _watch(worker: str, guard: str):
    # Stream during the entire capture; relying on the daemon's last 256 events would
    # discard evidence on busy hosts or large backups. Never persist other stacks' labels.
    proc = subprocess.Popen(
        [
            "docker",
            "events",
            "--since",
            _docker("info", "--format", "{{.SystemTime}}"),
            "--format",
            "{{json .}}",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    ready, done = threading.Event(), threading.Event()
    events = []

    def read():
        assert proc.stdout
        for line in proc.stdout:
            event = json.loads(line)
            act = event.get("Action", "")
            if act not in {
                "start",
                "die",
                "stop",
                "unpause",
                "restart",
                "pause",
                "destroy",
                "kill",
                "connect",
                "disconnect",
                "mount",
                "unmount",
            } and not act.startswith("exec_start"):
                continue
            attrs = event["Actor"].get("Attributes", {})
            event["Actor"]["Attributes"] = {
                k: attrs.get(k) for k in ("name", "container", "com.docker.compose.project")
            }
            events.append(event)
            if (
                event.get("Type") == "container"
                and event["Actor"]["ID"] == guard
                and act == "start"
            ):
                ready.set()
            if event.get("Type") == "container" and act == "die" and attrs.get("name") == worker:
                done.set()
                break

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        _docker("start", guard)
        if not ready.wait(10):
            raise RuntimeError("Docker event observer did not attach")
        yield events
        if not done.wait(10):
            raise RuntimeError("Docker event observer lost the capture boundary")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        reader.join(timeout=10)


def backup(args: argparse.Namespace) -> dict[str, Any]:
    engine = os.environ.get("DOCKER_HOST") or _docker(
        "context", "inspect", "--format", '{{(index .Endpoints "docker").Host}}'
    )
    if not engine.startswith(("npipe://", "unix://")):
        raise RuntimeError("a local Docker engine is required")
    project = args.project
    compose = ["compose", "--project-name", project]
    for path in args.compose_file:
        compose.extend(("-f", str(path.resolve(strict=True))))
    rows = _containers()
    storage = {
        role: _service(rows, project, name)["id"]
        for role, name in (
            ("primary", args.postgres),
            ("proxy", args.proxy_db),
            ("minio", args.minio),
        )
    }
    if storage["minio"] in (storage["primary"], storage["proxy"]):
        raise RuntimeError("object storage must refer to its own service")
    storage["checkpoint"] = (
        _service(rows, project, args.checkpoint_db)["id"]
        if args.checkpoint_db
        else storage["primary"]
    )
    app = _service(rows, project, args.api)
    proxy = _service(rows, project, args.proxy)
    expected_sources = {
        "primary": _configured_source(app, "DATABASE_URL"),
        "checkpoint": _configured_source(app, "DIRECTOR_CHECKPOINT_DATABASE_URL"),
        "proxy": _configured_source(proxy, "DATABASE_URL"),
        "minio": _configured_source(app, "MINIO_ENDPOINT", object_store=True),
    }
    _, _, protected_paths = _scope(rows, project, storage, stopped=False)
    repo = args.repository.resolve(strict=True)
    staging = args.staging_parent.resolve(strict=True)
    key = args.password_file.resolve(strict=True)
    report = args.report.resolve()
    if (
        not repo.is_dir()
        or not staging.is_dir()
        or not key.is_file()
        or any(
            _overlap(p.as_posix(), src)
            for p in (repo, staging, key, report)
            for src in protected_paths
        )
        or any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate((repo, staging, key, report))
            for b in (repo, staging, key, report)[i + 1 :]
        )
    ):
        raise RuntimeError("repository, staging, password and report must use separate paths")
    writer_ids = [
        r["id"]
        for r in rows.values()
        if r["project"] == project and r["id"] not in storage.values() and r["state"] == "running"
    ]
    if any(
        rows[i]["service"] in {"migrate", "database-bootstrap", "litellm-bootstrap", "maintenance"}
        for i in writer_ids
    ):
        raise RuntimeError("another maintenance or migration action is running")
    # Front door first, durable storage last; restart only the same originally running containers.
    priority = [
        "frontend",
        "api",
        "dispatcher",
        "worker-default",
        "worker-director",
        "worker-heavy",
        "litellm",
        "litellm-network",
        "redis",
    ]
    writer_ids.sort(
        key=lambda i: priority.index(rows[i]["service"]) if rows[i]["service"] in priority else 3
    )
    worker = f"{project}-capture-{uuid4().hex[:12]}"
    os.umask(0o077)
    with report.open("x", encoding="utf-8") as output:
        guard = _docker(
            "create",
            "--name",
            f"{project}-cold-backup-lock",
            "--network",
            "none",
            "--label",
            f"org.dramaforge.maintenance.project={project}",
            "--label",
            "org.dramaforge.maintenance.original-writers=" + ",".join(writer_ids),
            "--entrypoint",
            "true",
            app["image"],
        )
        stopped = []
        try:
            for ident in writer_ids:
                stopped.append(ident)
                _docker("stop", "--time", "75", ident)
            state = _containers()
            if any(
                state[i]["state"] != "exited" or state[i]["code"] not in {0, 143} for i in stopped
            ):
                raise RuntimeError("a writer did not stop gracefully")
            ips, nets, mounts = _scope(state, project, storage, stopped=True)
            with _watch(worker, guard) as events:
                _scope(_containers(), project, storage, stopped=True)
                raw = _docker(
                    *compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    "-T",
                    "--name",
                    worker,
                    "-v",
                    f"{repo}:/capture-repository",
                    "-v",
                    f"{staging}:/capture-staging",
                    "-v",
                    f"{key}:/capture-password:ro",
                    "--entrypoint",
                    "python",
                    args.maintenance,
                    "-m",
                    "app.maintenance.cold_capture",
                    data=json.dumps(
                        {
                            "storage_ips": ips,
                            "project": project,
                            "app_image": app["image"],
                            "proxy_image": proxy["image"],
                            "runtime_sources": expected_sources,
                        }
                    ),
                )
            _check_events(events, worker, nets, mounts, storage, project)
            _scope(_containers(), project, storage, stopped=True)
            receipt = json.loads(raw)
            if not receipt.get("snapshot_id") or not receipt.get("manifest_hash"):
                raise RuntimeError("capture produced no restorable snapshot")
            receipt.update(
                completed=True, verified_window="compose_offline", writers_stopped=len(stopped)
            )
        finally:
            _resume(rows, stopped)
            _docker("rm", guard)
        json.dump(receipt, output, sort_keys=True)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--compose-file", type=Path, action="append", required=True)
    parser.add_argument("--checkpoint-db", help="Compose storage service, if separate from primary")
    for field in ("repository", "staging-parent", "password-file", "report"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field, default in (
        ("postgres", "postgres"),
        ("proxy-db", "litellm-db"),
        ("minio", "minio"),
        ("api", "api"),
        ("proxy", "litellm"),
        ("maintenance", "maintenance"),
    ):
        parser.add_argument("--" + field, default=default)
    try:
        print(json.dumps(backup(parser.parse_args()), sort_keys=True))
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
