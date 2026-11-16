"""Real loopback sockets and subprocesses, without public feeds or market orders."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
from threading import Thread
import time
from urllib.request import urlopen

import pytest

from nory_standalone import __version__
from nory_standalone.__main__ import main
from nory_standalone.nory.config import Config
from nory_standalone.nory.launcher import (
    APP_ID,
    existing_nory,
    instance_id,
    reserve_endpoint,
)


@contextmanager
def local_service(routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_listener_is_reserved_and_not_rebound_while_server_initializes(tmp_path):
    identity = instance_id(Config(), tmp_path / "never-created.db")
    with reserve_endpoint(0, identity) as selected:
        assert not selected.reused
        with socket.socket() as contender, pytest.raises(OSError):
            contender.bind(("127.0.0.1", selected.port))
        port = selected.port
    with socket.socket() as after:
        after.bind(("127.0.0.1", port))
    assert not (tmp_path / "never-created.db").exists()


def test_unrelated_app_gets_an_alternative_port_without_opening_database(tmp_path):
    db = tmp_path / "untouched.db"
    identity = instance_id(Config(), db)
    with local_service({"/api/health": {"app": "someone-else"}}) as busy:
        with reserve_endpoint(busy, identity) as selected:
            assert not selected.reused and selected.port != busy
            assert selected.listener.getsockname() == ("127.0.0.1", selected.port)
        assert existing_nory(busy) is None
    assert not db.exists()


def test_second_launch_reuses_matching_instance_without_creating_a_worker(
    tmp_path, monkeypatch, capsys
):
    db = tmp_path / "same.db"
    identity = instance_id(Config(), db)
    routes = {
        "/api/health": {
            "app": APP_ID,
            "mode": "PAPER_ONLY",
            "version": __version__,
            "instance_id": identity,
        }
    }
    import nory_standalone.server as server

    def must_not_create(*args, **kwargs):
        raise AssertionError("A duplicate launch must never construct a second motor")

    monkeypatch.setattr(server, "create_app", must_not_create)
    with local_service(routes) as busy:
        assert (
            main(["--offline", "--no-browser", "--db", str(db), "--port", str(busy)])
            == 0
        )
        assert f"http://127.0.0.1:{busy}" in capsys.readouterr().out
    assert not db.exists()


def test_different_database_is_not_silently_replaced_by_existing_instance(tmp_path):
    identity = instance_id(Config(), tmp_path / "new.db")
    routes = {
        "/api/health": {
            "app": APP_ID,
            "mode": "PAPER_ONLY",
            "version": __version__,
            "instance_id": "another-experiment",
        }
    }
    with local_service(routes) as busy:
        with reserve_endpoint(busy, identity) as selected:
            assert not selected.reused and selected.port != busy


def test_legacy_nory_is_detected_without_reading_session_token():
    routes = {
        "/openapi.json": {
            "info": {"title": "NORY 2.0 · Paper Research", "version": "2.1.0"},
            "paths": {"/api/start": {}, "/api/stop": {}, "/api/status": {}},
        }
    }
    with local_service(routes) as busy:
        assert existing_nory(busy) == {
            "version": "2.1.0",
            "instance_id": None,
            "legacy": True,
        }
        with reserve_endpoint(busy, "unknown", allow_legacy=True) as target:
            assert target.reused and target.port == busy


def test_exhausted_port_range_has_a_clear_error():
    with local_service({}) as busy:
        with pytest.raises(OSError, match="No hay un puerto local disponible"):
            reserve_endpoint(busy, "none", alternatives=0)


def test_real_server_uses_reserved_socket_and_duplicate_cli_exits_cleanly(tmp_path):
    root = Path(__file__).resolve().parents[2]
    db = tmp_path / "server.sqlite3"
    # Dynamic port avoids interacting with any developer's actual local instance.
    with socket.socket() as free:
        free.bind(("127.0.0.1", 0))
        port = free.getsockname()[1]
    command = [
        sys.executable,
        "-m",
        "nory_standalone",
        "--offline",
        "--no-browser",
        "--db",
        str(db),
        "--port",
        str(port),
    ]
    with (tmp_path / "server.log").open("w") as output:
        process = subprocess.Popen(
            command, cwd=root, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            for _ in range(150):
                try:
                    with urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=0.3
                    ) as response:
                        health = json.load(response)
                    break
                except OSError:
                    if process.poll() is not None:
                        raise AssertionError((tmp_path / "server.log").read_text())
                    time.sleep(0.05)
            else:
                raise AssertionError("Test service never became ready")
            assert health["version"] == __version__ and health[
                "instance_id"
            ] == instance_id(Config(), db)
            duplicate = subprocess.run(
                command, cwd=root, capture_output=True, text=True, timeout=10
            )
            assert duplicate.returncode == 0, duplicate.stderr
            assert "Nory ya está abierto" in duplicate.stdout
            assert "10048" not in duplicate.stderr
            assert process.poll() is None
        finally:
            process.terminate()
            process.wait(timeout=10)
