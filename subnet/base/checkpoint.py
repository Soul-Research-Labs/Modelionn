"""State checkpoint for neuron persistence across restarts.

Writes a JSON file periodically so that in-memory state (prover scores,
pending jobs, miner stats) can survive process restarts.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path.home() / ".zkml" / "checkpoints"
_CHECKPOINT_INTERVAL_SECS = 60  # default: save every 60s


class Checkpoint:
    """JSON-based state checkpoint manager."""

    def __init__(self, name: str, directory: str | Path | None = None) -> None:
        self._name = name
        self._dir = Path(directory) if directory else _DEFAULT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / f"{name}.json"
        self._last_save: float = 0

    @property
    def path(self) -> Path:
        return self._path

    def save(self, state: dict[str, Any], *, force: bool = False) -> None:
        """Atomically write state to disk.

        Skips the write if less than ``_CHECKPOINT_INTERVAL_SECS`` have
        elapsed since the last save, unless *force* is True.
        """
        now = time.monotonic()
        if not force and (now - self._last_save) < _CHECKPOINT_INTERVAL_SECS:
            return

        # Atomic write: write to temp file then rename
        try:
            fd, tmp = tempfile.mkstemp(
                dir=self._dir, prefix=f".{self._name}_", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(state, f, default=str)
            except BaseException:
                os.close(fd) if not f.closed else None  # type: ignore[union-attr]
                raise
            os.replace(tmp, self._path)
            self._last_save = now
            logger.debug("Checkpoint saved: %s (%d keys)", self._path, len(state))
        except Exception as exc:
            logger.warning("Checkpoint save failed (%s): %s", self._path, exc)
            # Clean up temp file on failure
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def load(self) -> dict[str, Any]:
        """Load last checkpoint. Returns empty dict if none exists."""
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text())
            logger.info("Checkpoint loaded: %s (%d keys)", self._path, len(data))
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Checkpoint load failed (%s): %s", self._path, exc)
            return {}
