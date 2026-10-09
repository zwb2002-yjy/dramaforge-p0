"""Director heartbeat health CLI: fail closed without importing worker jobs."""

from __future__ import annotations

import ast
import builtins
import inspect
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from arq.constants import health_check_key_suffix
from arq.worker import Worker
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_compose_director_healthcheck_is_lean() -> None:
    services = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())["services"]
    director = services["worker-director"]
    assert director["healthcheck"] == {
        "test": ["CMD", "python", "-m", "app.workers.healthcheck"],
        "interval": "15s",
        "timeout": "5s",
        "retries": 5,
    }
    assert director["command"] == ["arq", "app.workers.director.WorkerSettings"]
    assert "REDIS_URL" in director["environment"]
    assert "DIRECTOR_QUEUE_NAME" in director["environment"]


@pytest.fixture
def redis_factory(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    factory = MagicMock()
    client = factory.return_value.__enter__.return_value
    client.pipeline.return_value.__enter__.return_value.execute.return_value = [b"alive", 1000]
    monkeypatch.setattr(Redis, "from_url", factory)
    monkeypatch.setenv("REDIS_URL", "redis://unused:6379/2")
    monkeypatch.setenv("DIRECTOR_QUEUE_NAME", "custom:director")
    return factory


@pytest.mark.parametrize(
    ("value", "ttl_ms", "expected"),
    [
        (b"alive", 3_601_000, 0),
        (b"alive", 1, 0),
        (None, -2, 1),  # missing or expired key
        (b"", 1000, 1),
        (b"stale", 0, 1),
        (b"stale", -1, 1),  # a persistent sentinel is not a worker heartbeat
        (b"stale", -2, 1),  # expiry between pipelined GET and PTTL
        (b"invalid lifetime", 3_601_001, 1),
    ],
)
def test_cli_requires_nonempty_expiring_heartbeat(
    redis_factory: MagicMock,
    capsys: pytest.CaptureFixture[str],
    value: bytes | None,
    ttl_ms: int,
    expected: int,
) -> None:
    from app.workers import healthcheck

    client = redis_factory.return_value.__enter__.return_value
    pipe = client.pipeline.return_value.__enter__.return_value
    pipe.execute.return_value = [value, ttl_ms]
    assert healthcheck.main() == expected
    client.pipeline.assert_called_once_with(transaction=False)
    pipe.get.assert_called_once_with("custom:director:health-check")
    pipe.pttl.assert_called_once_with("custom:director:health-check")
    client.ping.assert_not_called()
    client.set.assert_not_called()
    redis_factory.return_value.__exit__.assert_called_once()
    output = capsys.readouterr()
    assert ("Health check successful" in output.out) is (expected == 0)
    assert ("Health check failed" in output.err) is (expected == 1)


def test_wrong_queue_cannot_borrow_another_queues_heartbeat(redis_factory: MagicMock) -> None:
    from app.workers import healthcheck

    pipe = redis_factory.return_value.__enter__.return_value.pipeline.return_value
    pipe = pipe.__enter__.return_value
    seen_keys: list[str] = []
    pipe.get.side_effect = lambda key: seen_keys.append(key)
    # A different queue is alive, but the configured Director queue has no sentinel.
    heartbeats = {"dramaforge:default:health-check": [b"alive", 1000]}
    pipe.execute.side_effect = lambda: heartbeats.get(seen_keys[-1], [None, -2])
    assert healthcheck.main() == 1
    assert seen_keys == ["custom:director:health-check"]


def test_connection_failure_fails_closed_without_leaking_credentials(
    redis_factory: MagicMock, capsys: pytest.CaptureFixture[str],
) -> None:
    from app.workers import healthcheck

    pipe = redis_factory.return_value.__enter__.return_value.pipeline.return_value
    pipe.__enter__.return_value.execute.side_effect = RedisConnectionError(
        "redis://user:private-password@unreachable:6379/0"
    )
    assert healthcheck.main() == 1
    output = capsys.readouterr()
    assert "ConnectionError" in output.err
    assert "private-password" not in output.err
    assert "successful" not in output.out
    redis_factory.return_value.__exit__.assert_called_once()


def test_close_failure_is_not_reported_as_success(
    redis_factory: MagicMock, capsys: pytest.CaptureFixture[str],
) -> None:
    from app.workers import healthcheck

    redis_factory.return_value.__exit__.side_effect = OSError("close failed")
    assert healthcheck.main() == 1
    assert "successful" not in capsys.readouterr().out


@pytest.mark.parametrize("variable", ["REDIS_URL", "DIRECTOR_QUEUE_NAME"])
def test_empty_configuration_fails_before_connecting(
    monkeypatch: pytest.MonkeyPatch, redis_factory: MagicMock, variable: str,
) -> None:
    from app.workers import healthcheck

    monkeypatch.setenv(variable, "")
    assert healthcheck.main() == 1
    redis_factory.assert_not_called()


def test_missing_redis_url_does_not_fall_back_to_another_redis(
    monkeypatch: pytest.MonkeyPatch, redis_factory: MagicMock,
) -> None:
    from app.workers import healthcheck

    monkeypatch.delenv("REDIS_URL")
    assert healthcheck.main() == 1
    redis_factory.assert_not_called()


def test_network_timeouts_and_retries_are_bounded(redis_factory: MagicMock) -> None:
    from app.workers import healthcheck

    assert healthcheck.main() == 0
    args, kwargs = redis_factory.call_args
    assert args == ("redis://unused:6379/2",)
    assert kwargs["socket_connect_timeout"] == 1
    assert kwargs["socket_timeout"] == 1
    assert kwargs["retry_on_timeout"] is False
    retry = kwargs["retry"]
    attempts = 0

    def fail() -> None:
        nonlocal attempts
        attempts += 1
        raise RedisConnectionError("offline")

    with pytest.raises(RedisConnectionError):
        retry.call_with_retry(fail, lambda error: None)
    assert attempts == 1


@pytest.mark.parametrize("phase", ["import", "connect", "read", "close"])
def test_deadline_includes_import_connect_read_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, redis_factory: MagicMock, phase: str,
) -> None:
    from app.workers import healthcheck

    monkeypatch.setattr(healthcheck, "PROBE_TIMEOUT_SECONDS", 0.05)
    if phase == "import":
        original_import = builtins.__import__

        def delayed_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "redis":
                time.sleep(2)
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", delayed_import)
    else:
        if phase == "connect":
            target = redis_factory
        elif phase == "read":
            pipe = redis_factory.return_value.__enter__.return_value.pipeline.return_value
            target = pipe.__enter__.return_value.execute
        else:
            target = redis_factory.return_value.__exit__
        target.side_effect = lambda *args, **kwargs: time.sleep(2)
    old_handler = signal.getsignal(signal.SIGALRM)
    start = time.monotonic()
    assert healthcheck.main() == 1
    assert time.monotonic() - start < 1
    assert signal.getsignal(signal.SIGALRM) == old_handler
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_arq_heartbeat_contract_has_not_drifted(
    monkeypatch: pytest.MonkeyPatch, redis_factory: MagicMock,
) -> None:
    from app.workers import healthcheck

    assert health_check_key_suffix == ":health-check"
    interval = inspect.signature(Worker).parameters["health_check_interval"].default
    assert (interval + 1) * 1000 == healthcheck.MAX_HEARTBEAT_TTL_MS
    tree = ast.parse((REPO_ROOT / "backend/app/workers/director.py").read_text())
    queue_assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "QUEUE_NAME"
            for target in node.targets
        )
    )
    assert isinstance(queue_assignment.value, ast.Call)
    default_queue = ast.literal_eval(queue_assignment.value.args[1])
    settings = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    for node in settings.body:
        if isinstance(node, ast.Assign):
            assert not any(
                isinstance(target, ast.Name)
                and target.id in {"health_check_interval", "health_check_key"}
                for target in node.targets
            ), "Update health CLI when WorkerSettings overrides the Arq heartbeat contract"
    monkeypatch.delenv("DIRECTOR_QUEUE_NAME")
    assert healthcheck.main() == 0
    pipe = redis_factory.return_value.__enter__.return_value.pipeline.return_value
    pipe.__enter__.return_value.get.assert_called_once_with(default_queue + health_check_key_suffix)


def test_cli_does_not_import_business_modules_and_unreachable_redis_fails() -> None:
    code = """
import importlib.abc, runpy, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('arq', 'sqlalchemy', 'app.config', 'app.director',
                                'app.providers', 'app.workers.director', 'app.workers.jobs')):
            raise AssertionError('business import: ' + fullname)
sys.meta_path.insert(0, Guard())
runpy.run_module('app.workers.healthcheck', run_name='__main__')
"""
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        env={**os.environ, "REDIS_URL": "redis://127.0.0.1:1/0"},
        capture_output=True, text=True, timeout=5, check=False,
    )
    assert time.monotonic() - start < 5
    assert result.returncode == 1
    assert "ConnectionError" in result.stderr
    assert "AssertionError" not in result.stderr
    assert "successful" not in result.stdout
