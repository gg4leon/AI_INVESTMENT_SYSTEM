"""Reserve the loopback listener BEFORE starting a database or market worker."""

from dataclasses import dataclass
import errno
import hashlib
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import socket

from .storage import resolve_database

APP_ID = "nory-paper-research"


def instance_id(cfg, db_path):
    path, _ = resolve_database(db_path, cfg)
    canonical = os.path.normcase(str(Path(path).resolve()))
    return hashlib.sha256((canonical + ":" + cfg.fingerprint()).encode()).hexdigest()


def _local_json(port, path):
    # Loopback stays local even when the machine has a corporate HTTP proxy.
    connection = HTTPConnection("127.0.0.1", port, timeout=0.6)
    try:
        connection.request("GET", path, headers={"Accept": "application/json"})
        response = connection.getresponse()
        if (
            response.status != 200
            or response.getheader("Content-Type", "").split(";")[0].strip()
            != "application/json"
        ):
            return None
        raw = response.read(65_537)
        if response.status != 200 or len(raw) > 65_536:
            return None
        result = json.loads(raw)
        return result if isinstance(result, dict) else None
    except (OSError, ValueError, HTTPException):
        return None
    finally:
        connection.close()


def existing_nory(port):
    health = _local_json(port, "/api/health")
    if health and health.get("app") == APP_ID and health.get("mode") == "PAPER_ONLY":
        return {
            "version": str(health.get("version", "desconocida"))[:32],
            "instance_id": health.get("instance_id"),
            "legacy": False,
        }
    # Releases 2.0/2.1.0 predate /api/health. OpenAPI has no session token or balances.
    schema = _local_json(port, "/openapi.json")
    if schema:
        info, paths = schema.get("info", {}), schema.get("paths", {})
        if (
            isinstance(info, dict)
            and isinstance(paths, dict)
            and info.get("title") == "NORY 2.0 · Paper Research"
            and all(p in paths for p in ("/api/start", "/api/stop", "/api/status"))
        ):
            return {
                "version": str(info.get("version", "desconocida"))[:32],
                "instance_id": None,
                "legacy": True,
            }
    return None


@dataclass
class LaunchTarget:
    port: int
    listener: socket.socket | None
    existing_version: str | None = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    @property
    def reused(self):
        return self.listener is None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.listener is not None:
            self.listener.close()


def reserve_endpoint(preferred, identity, *, allow_legacy=False, alternatives=10):
    if not 0 <= preferred <= 65535:
        raise ValueError("Puerto inválido")
    last_error = None
    for port in range(preferred, min(65535, preferred + alternatives) + 1):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(128)
            listener.setblocking(False)
            return LaunchTarget(listener.getsockname()[1], listener)
        except OSError as exc:
            listener.close()
            if exc.errno not in (errno.EADDRINUSE, errno.EACCES) and getattr(
                exc, "winerror", None
            ) not in (10048, 10013):
                raise
            last_error = exc
            existing = existing_nory(port)
            if existing and (
                existing["instance_id"] == identity
                or (existing["legacy"] and allow_legacy)
            ):
                return LaunchTarget(port, None, existing["version"])
    raise OSError(
        f"No hay un puerto local disponible entre {preferred} y {min(65535, preferred + alternatives)}. Cierra la instancia anterior o indica --port."
    ) from last_error
