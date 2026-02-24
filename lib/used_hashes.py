from __future__ import annotations

import threading
import time
from typing import Dict


class UsedHashSet:
    def __init__(
        self,
        ttl_seconds: int = 3600,
        cleanup_interval_seconds: int = 300,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

        self._lock = threading.Lock()
        self._used_hashes: Dict[str, float] = {}
        self._last_cleanup = 0.0

    def is_used(self, payment_hash: str) -> bool:
        payment_hash = payment_hash.lower()
        if not payment_hash:
            return False

        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            return payment_hash in self._used_hashes

    def mark_used(self, payment_hash: str) -> bool:
        payment_hash = payment_hash.lower()
        if not payment_hash:
            return False

        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            if payment_hash in self._used_hashes:
                return False
            self._used_hashes[payment_hash] = now
            return True

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            self._cleanup(now)

    def stats(self) -> Dict[str, int]:
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            count = len(self._used_hashes)
            return {
                "pending": 0,
                "used": count,
                "known_used_hashes": count,
            }

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup >= self.cleanup_interval_seconds:
            self._cleanup(now)

    def _cleanup(self, now: float) -> None:
        used_expire_before = now - self.ttl_seconds
        self._used_hashes = {
            payment_hash: ts
            for payment_hash, ts in self._used_hashes.items()
            if ts >= used_expire_before
        }
        self._last_cleanup = now
