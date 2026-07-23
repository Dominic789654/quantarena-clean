"""Date-partitioned snapshot store for alt-data providers.

Mirrors the Tavily news snapshot semantics (mode: off | prefer_local |
refresh | local_only) but partitions snapshots by capture date so that
ephemeral sources (Reddit mentions, EDGAR search results) can be replayed
for a historical trading date once daily capture has been running.

Layout: {snapshot_dir}/{key}/{YYYY-MM-DD}.json with payload envelope
{"captured_at": iso-ts, "payload": <raw provider JSON>}.

Modes:
- off:          no snapshot reads or writes (default; live behavior only)
- refresh:      always fetch live, but persist a snapshot for today
- prefer_local: serve today's (or as_of's) snapshot when present, else
                fetch live and persist
- local_only:   replay mode — serve the nearest snapshot at or before
                as_of within the lookback window; never touch the network
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

VALID_MODES = {"off", "prefer_local", "refresh", "local_only"}
DEFAULT_LOOKBACK_DAYS = 7


class SnapshotStore:
    """File-backed, date-partitioned snapshot store for one provider.

    Note: snapshot days are keyed by the capture host's local calendar date
    (date.today()); if the host timezone crosses midnight during the target
    market's trading session, capture and replay day-keys can differ by one.
    Run daily capture in (or aligned to) the market's timezone.
    """

    # One lock per provider prefix: same-file writers synchronize without
    # unrelated providers serializing on each other.
    _locks: dict = {}
    _locks_guard = threading.Lock()

    def __init__(self, env_prefix: str, default_dir: str):
        self.env_prefix = env_prefix
        self.default_dir = default_dir
        with SnapshotStore._locks_guard:
            self._lock = SnapshotStore._locks.setdefault(env_prefix, threading.Lock())

    # Env is read per call so tests and long-lived processes can flip modes.
    @property
    def mode(self) -> str:
        raw = os.getenv(f"{self.env_prefix}_SNAPSHOT_MODE", "off").strip().lower()
        return raw if raw in VALID_MODES else "off"

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def snapshot_dir(self) -> Path:
        raw = os.getenv(f"{self.env_prefix}_SNAPSHOT_DIR", self.default_dir)
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path

    @property
    def lookback_days(self) -> int:
        raw = os.getenv(f"{self.env_prefix}_SNAPSHOT_LOOKBACK_DAYS", "")
        try:
            return max(0, int(raw))
        except ValueError:
            return DEFAULT_LOOKBACK_DAYS

    @staticmethod
    def _safe_key(key: str) -> Path:
        parts = []
        for part in key.split("/"):
            cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", part)[:80]
            # Dot-only segments ("."/"..") would escape the snapshot dir.
            if not cleaned or not cleaned.strip("."):
                cleaned = "_"
            parts.append(cleaned)
        return Path(*parts) if parts else Path("item")

    def _path_for(self, key: str, day: date) -> Path:
        return self.snapshot_dir / self._safe_key(key) / f"{day.isoformat()}.json"

    @staticmethod
    def _coerce_day(as_of: Optional[date | datetime]) -> date:
        if as_of is None:
            return date.today()
        if isinstance(as_of, datetime):
            return as_of.date()
        return as_of

    def load_exact(self, key: str, as_of: Optional[date | datetime] = None) -> Optional[Any]:
        """Load the snapshot captured exactly on as_of (default today)."""
        path = self._path_for(key, self._coerce_day(as_of))
        if not path.exists():
            return None
        with self._lock:
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return envelope.get("payload")

    def load_nearest(self, key: str, as_of: Optional[date | datetime] = None) -> Optional[Any]:
        """Load the newest snapshot at or before as_of within the lookback window."""
        day = self._coerce_day(as_of)
        for offset in range(self.lookback_days + 1):
            payload = self.load_exact(key, day - timedelta(days=offset))
            if payload is not None:
                return payload
        return None

    def has_for_day(self, key: str, as_of: Optional[date | datetime] = None) -> bool:
        """Cheap existence check without parsing the snapshot payload."""
        return self._path_for(key, self._coerce_day(as_of)).exists()

    def save(self, key: str, payload: Any) -> Optional[Path]:
        """Persist a snapshot for today. Never raises; returns the path or None.

        Written atomically (temp file + os.replace) so a concurrent replay
        process never observes a torn file.
        """
        path = self._path_for(key, date.today())
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            envelope = {
                "captured_at": datetime.now().isoformat(timespec="seconds"),
                "payload": payload,
            }
            content = json.dumps(envelope, ensure_ascii=False, default=str)
            tmp_path = path.with_suffix(f".tmp-{os.getpid()}")
            with self._lock:
                tmp_path.write_text(content, encoding="utf-8")
                os.replace(tmp_path, path)
            return path
        except Exception:
            return None
