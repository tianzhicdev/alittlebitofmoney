from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class InvoiceRecord:
    invoice: str
    api_name: str
    endpoint_path: str
    amount_sats: int
    request_bytes: bytes
    request_content_type: str
    created_at: float
    status: str = "pending"
    used_at: Optional[float] = None


class InvoiceStore:
    def __init__(
        self,
        invoice_ttl_seconds: int = 1800,
        used_hash_ttl_seconds: int = 3600,
        cleanup_interval_seconds: int = 300,
    ) -> None:
        self.invoice_ttl_seconds = invoice_ttl_seconds
        self.used_hash_ttl_seconds = used_hash_ttl_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

        self._lock = threading.Lock()
        self._invoices: Dict[str, InvoiceRecord] = {}
        self._used_hashes: Dict[str, float] = {}
        self._last_cleanup = 0.0

    def add(self, payment_hash: str, record: InvoiceRecord) -> None:
        payment_hash = payment_hash.lower()
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            self._invoices[payment_hash] = record

    def get(self, payment_hash: str) -> Optional[InvoiceRecord]:
        payment_hash = payment_hash.lower()
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            return self._invoices.get(payment_hash)

    def is_used(self, payment_hash: str) -> bool:
        payment_hash = payment_hash.lower()
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            return payment_hash in self._used_hashes

    def mark_used(self, payment_hash: str) -> bool:
        payment_hash = payment_hash.lower()
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            record = self._invoices.get(payment_hash)
            if record is None or record.status == "used":
                return False
            record.status = "used"
            record.used_at = now
            self._used_hashes[payment_hash] = now
            return True

    def delete(self, payment_hash: str) -> None:
        payment_hash = payment_hash.lower()
        with self._lock:
            self._invoices.pop(payment_hash, None)

    def is_expired(self, payment_hash: str, ttl_seconds: int) -> bool:
        payment_hash = payment_hash.lower()
        now = time.time()
        with self._lock:
            record = self._invoices.get(payment_hash)
            if record is None:
                return False
            return now > (record.created_at + ttl_seconds)

    def cleanup(self) -> None:
        now = time.time()
        with self._lock:
            self._cleanup(now)

    def stats(self) -> Dict[str, int]:
        now = time.time()
        with self._lock:
            self._maybe_cleanup(now)
            pending = 0
            used = 0
            for record in self._invoices.values():
                if record.status == "pending":
                    pending += 1
                else:
                    used += 1
            return {
                "pending": pending,
                "used": used,
                "known_used_hashes": len(self._used_hashes),
            }

    def _maybe_cleanup(self, now: float) -> None:
        if now - self._last_cleanup >= self.cleanup_interval_seconds:
            self._cleanup(now)

    def _cleanup(self, now: float) -> None:
        expire_before = now - self.invoice_ttl_seconds
        self._invoices = {
            payment_hash: record
            for payment_hash, record in self._invoices.items()
            if record.created_at >= expire_before
        }

        used_expire_before = now - self.used_hash_ttl_seconds
        self._used_hashes = {
            payment_hash: ts
            for payment_hash, ts in self._used_hashes.items()
            if ts >= used_expire_before
        }
        self._last_cleanup = now
