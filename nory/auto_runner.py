"""A single, opt-in background Nory MicroLab loop for the local Streamlit server.

No network, no brokers, and no real trades. The loop exists only while the
local Python/Streamlit process stays alive. In a multi-process Streamlit
deployment each process needs a separate coordinator; do NOT deploy remotely.
"""
from datetime import datetime, timezone
from pathlib import Path
import json
from threading import Event, RLock, Thread
import time

from nory.micro_feed import SCENARIOS
from nory.micro_lab import (
    DEFAULT_DB, _validate_universe, dashboard, process_second, set_paused,
)


class MicroAutoRunner:
    """Thread-safe, single worker per Streamlit process; not an OS scheduler."""

    def __init__(
        self, db_path: str | Path = DEFAULT_DB, *,
        processor=process_second, snapshot_reader=dashboard,
        pause_writer=set_paused,
    ):
        self._db_path = Path(db_path)
        self._processor = processor
        self._snapshot_reader = snapshot_reader
        self._pause_writer = pause_writer
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._status = "IDLE"
        self._last_result: dict | None = None
        self._last_error: str | None = None
        self._cycles = 0
        self._started_at: str | None = None
        self._symbols: tuple[str, ...] = ()
        self._scenario: str | None = None
        self._interval = 1.0

    def status(self) -> dict:
        with self._lock:
            running = self._thread is not None and self._thread.is_alive()
            return {
                "running": running,
                "status": self._status,
                "cycles_this_run": self._cycles,
                "last_result": dict(self._last_result) if self._last_result else None,
                "last_error": self._last_error,
                "started_at_utc": self._started_at,
                "interval_seconds": self._interval,
                "scenario": self._scenario,
                "symbols": list(self._symbols),
                "mode": "SYNTHETIC_ONLY",
            }

    def start(self, symbols, scenario="mixed", interval_seconds=1.0) -> dict:
        """Explicitly start on user click; refuses multiple loops and bad state."""
        if scenario not in SCENARIOS:
            raise ValueError("Unknown synthetic scenario")
        if not .2 <= interval_seconds <= 60:
            raise ValueError("Interval must be between 0.2 and 60 seconds")
        symbols = _validate_universe(tuple(symbols))
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return {"started": False, "reason": "ALREADY_RUNNING"}

            current = self._snapshot_reader(db_path=self._db_path)["state"]
            if current["halted"]:
                raise ValueError("Risk circuit halted the portfolio; no automatic restart")
            if current["universe_json"] is not None:
                if json.loads(current["universe_json"]) != list(symbols):
                    raise ValueError("This session has a fixed universe: use its existing symbols")
                if current["scenario"] != scenario:
                    raise ValueError("This session has a fixed scenario")

            self._stop_event = Event()
            self._status = "STARTING"
            self._last_error = None
            self._last_result = None
            self._cycles = 0
            self._started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._symbols = symbols
            self._scenario = scenario
            self._interval = float(interval_seconds)

            # Default PAUSED state is only changed after explicit user action.
            try:
                self._pause_writer(False, db_path=self._db_path)
                worker = Thread(
                    target=self._loop, name="Nory-MicroLab-Auto",
                    daemon=True,
                )
                self._thread = worker
                worker.start()
            except Exception:
                self._status = "ERROR_START"
                self._pause_writer(True, db_path=self._db_path)
                raise
            return {"started": True, "reason": "STARTED"}

    def _loop(self):
        next_time = time.monotonic()
        try:
            while not self._stop_event.is_set():
                # Do not call any Streamlit function from this thread.
                result = self._processor(
                    symbols=self._symbols, scenario=self._scenario,
                    db_path=self._db_path,
                )
                with self._lock:
                    self._last_result = result
                    if result.get("status") == "PROCESSED":
                        self._cycles += 1
                        self._status = "RUNNING"
                    else:
                        self._status = result.get("status", "STOPPED")
                if result.get("status") != "PROCESSED":
                    break
                # Never burst many cycles to catch up after a slow tick.
                next_time = max(next_time + self._interval, time.monotonic())
                if self._stop_event.wait(max(0., next_time - time.monotonic())):
                    break
        except Exception as exc:
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
                self._status = "ERROR"
        finally:
            # Ensure a crashed/stopped worker does not leave portfolio armed.
            try:
                self._pause_writer(True, db_path=self._db_path)
            except Exception as exc:
                with self._lock:
                    self._last_error = (
                        (self._last_error + "; " if self._last_error else "")
                        + f"Pause failed: {type(exc).__name__}"
                    )
            with self._lock:
                if self._status in ("RUNNING", "STARTING"):
                    self._status = "STOPPED"

    def stop(self, *, wait_seconds=5.0) -> dict:
        """Stop at the next safe point; SQLite transaction finishes atomically."""
        self._stop_event.set()
        self._pause_writer(True, db_path=self._db_path)
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=wait_seconds)
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._status = "STOPPING"
            elif self._status not in ("ERROR", "CIRCUIT_HALTED"):
                self._status = "STOPPED"
        return self.status()
