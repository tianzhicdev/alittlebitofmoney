from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse

import asyncpg


class TopupError(Exception):
    pass


class TopupInvalidToken(TopupError):
    pass


class TopupInvalidPayment(TopupError):
    pass


class TopupInvoiceAlreadyClaimed(TopupError):
    pass


class TopupMissingToken(TopupError):
    pass


class TopupInsufficientBalance(TopupError):
    def __init__(self, balance_sats: int, required_sats: int) -> None:
        super().__init__("insufficient balance")
        self.balance_sats = balance_sats
        self.required_sats = required_sats


@dataclass
class TopupClaimResult:
    token: str
    balance_sats: int


class SupabaseTopupStore:
    def __init__(
        self,
        project_url: str,
        db_password: str,
        secret_key: str = "",
    ) -> None:
        self.project_url = project_url.strip()
        self.db_password = db_password.strip()
        self.secret_key = secret_key.strip()
        self.enabled = bool(self.project_url and self.db_password)
        self._dsn = ""
        self._dsn_candidates = (
            self._build_dsn_candidates(self.project_url, self.db_password)
            if self.enabled
            else []
        )
        self._pool: Optional[asyncpg.Pool] = None
        self.ready = False

    @classmethod
    def from_env(cls) -> "SupabaseTopupStore":
        return cls(
            project_url=os.getenv("ALITTLEBITOFMONEY_SUPABASE_PROJECT_URL", ""),
            db_password=os.getenv("ALITTLEBITOFMONEY_SUPABASE_PW", ""),
            secret_key=os.getenv("ALITTLEBITOFMONEY_SUPABASE_SECRET_KEY", ""),
        )

    async def startup(self) -> None:
        if not self.enabled:
            return
        if not self._dsn_candidates:
            print("WARNING: Supabase topup store disabled due to invalid project URL")
            return

        last_error: Optional[Exception] = None
        for name, dsn in self._dsn_candidates:
            try:
                self._pool = await asyncpg.create_pool(
                    dsn=dsn,
                    min_size=1,
                    max_size=5,
                    command_timeout=30,
                    statement_cache_size=0,
                )
                await self._ensure_schema()
                self._dsn = dsn
                self.ready = True
                print(f"Supabase topup store connected via {name}")
                return
            except Exception as exc:
                last_error = exc
                self.ready = False
                if self._pool is not None:
                    await self._pool.close()
                    self._pool = None

        print(f"WARNING: Supabase topup store unavailable: {last_error}")

    async def shutdown(self) -> None:
        self.ready = False
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def create_account(self) -> tuple[str, str]:
        """Create a new account with 0 balance. Returns (account_id, token)."""
        pool = self._require_pool()
        token = self._new_token()
        token_hash = self._hash_token(token)
        account_id = uuid.uuid4()
        async with pool.acquire() as conn:
            await conn.execute(
                "insert into accounts (id, token_hash, balance_sats) values ($1, $2, 0)",
                account_id,
                token_hash,
            )
        return str(account_id), token

    async def get_account_id_by_token(self, token: str) -> str:
        pool = self._require_pool()
        token_hash = self._hash_token(token)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select id from accounts where token_hash = $1",
                token_hash,
            )
        if row is None:
            raise TopupInvalidToken()
        return str(row["id"])

    async def create_topup_invoice(
        self,
        payment_hash: str,
        amount_sats: int,
        account_id: Optional[str],
    ) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                insert into topup_invoices (payment_hash, account_id, amount_sats, status)
                values ($1, $2, $3, 'pending')
                on conflict (payment_hash) do update
                  set account_id = excluded.account_id,
                      amount_sats = excluded.amount_sats,
                      status = 'pending',
                      created_at = now()
                """,
                payment_hash,
                account_id,
                amount_sats,
            )

    async def debit_token_balance(self, token: str, amount_sats: int, endpoint: str) -> int:
        pool = self._require_pool()
        token_hash = self._hash_token(token)
        async with pool.acquire() as conn:
            async with conn.transaction():
                account_row = await conn.fetchrow(
                    """
                    select id, balance_sats
                    from accounts
                    where token_hash = $1
                    for update
                    """,
                    token_hash,
                )
                if account_row is None:
                    raise TopupInvalidToken()

                balance_sats = int(account_row["balance_sats"])
                if balance_sats < amount_sats:
                    raise TopupInsufficientBalance(
                        balance_sats=balance_sats,
                        required_sats=amount_sats,
                    )

                updated_row = await conn.fetchrow(
                    """
                    update accounts
                    set balance_sats = balance_sats - $1,
                        updated_at = now()
                    where id = $2
                    returning balance_sats
                    """,
                    amount_sats,
                    account_row["id"],
                )
                await conn.execute(
                    """
                    insert into usage_log (account_id, endpoint, amount_sats)
                    values ($1, $2, $3)
                    """,
                    account_row["id"],
                    endpoint,
                    amount_sats,
                )
                return int(updated_row["balance_sats"])

    async def claim_topup_invoice(
        self,
        payment_hash: str,
        token: Optional[str],
    ) -> TopupClaimResult:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                invoice_row = await conn.fetchrow(
                    """
                    select payment_hash, account_id, amount_sats, status
                    from topup_invoices
                    where payment_hash = $1
                    for update
                    """,
                    payment_hash,
                )
                if invoice_row is None:
                    raise TopupInvalidPayment()
                if str(invoice_row["status"]) != "pending":
                    raise TopupInvoiceAlreadyClaimed()

                account_id: Optional[uuid.UUID] = invoice_row["account_id"]
                issued_token = token.strip() if token else ""

                if issued_token:
                    token_hash = self._hash_token(issued_token)
                    account_row = await conn.fetchrow(
                        """
                        select id
                        from accounts
                        where token_hash = $1
                        for update
                        """,
                        token_hash,
                    )
                    if account_row is None:
                        raise TopupInvalidToken()
                    selected_account_id = account_row["id"]
                    if account_id is not None and account_id != selected_account_id:
                        raise TopupInvalidPayment()
                elif account_id is not None:
                    raise TopupMissingToken()
                else:
                    issued_token = self._new_token()
                    token_hash = self._hash_token(issued_token)
                    selected_account_id = uuid.uuid4()
                    await conn.execute(
                        """
                        insert into accounts (id, token_hash, balance_sats)
                        values ($1, $2, 0)
                        """,
                        selected_account_id,
                        token_hash,
                    )

                balance_row = await conn.fetchrow(
                    """
                    update accounts
                    set balance_sats = balance_sats + $1,
                        updated_at = now()
                    where id = $2
                    returning balance_sats
                    """,
                    int(invoice_row["amount_sats"]),
                    selected_account_id,
                )
                await conn.execute(
                    """
                    update topup_invoices
                    set status = 'paid',
                        account_id = $1
                    where payment_hash = $2
                    """,
                    selected_account_id,
                    payment_hash,
                )

        return TopupClaimResult(
            token=issued_token,
            balance_sats=int(balance_row["balance_sats"]),
        )

    async def _ensure_schema(self) -> None:
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                create table if not exists accounts (
                  id uuid primary key,
                  token_hash text unique not null,
                  balance_sats bigint not null default 0 check (balance_sats >= 0),
                  created_at timestamptz not null default now(),
                  updated_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                """
                create table if not exists topup_invoices (
                  payment_hash text primary key,
                  account_id uuid references accounts(id),
                  amount_sats bigint not null check (amount_sats > 0),
                  status text not null default 'pending'
                    check (status in ('pending', 'paid', 'expired')),
                  created_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                """
                create table if not exists usage_log (
                  id bigserial primary key,
                  account_id uuid references accounts(id) not null,
                  endpoint text not null,
                  amount_sats bigint not null check (amount_sats >= 0),
                  created_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                "create index if not exists idx_usage_log_account_id on usage_log (account_id, created_at desc);"
            )

    @property
    def pool(self) -> Optional[asyncpg.Pool]:
        return self._pool

    def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Topup store is not ready")
        return self._pool

    @staticmethod
    def _new_token() -> str:
        return f"abl_{secrets.token_urlsafe(32)}"

    @staticmethod
    def _hash_token(token: str) -> str:
        token = token.strip()
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _build_dsn_candidates(project_url: str, password: str) -> list[tuple[str, str]]:
        parsed = urlparse(project_url)
        host = parsed.netloc or project_url
        host = host.split("/")[0]
        project_ref = host.split(".", 1)[0]
        if not project_ref:
            return []

        quoted_pw = quote_plus(password)
        candidates: list[tuple[str, str]] = []

        # Direct DB host can be IPv6-only, but try it first for lowest latency.
        db_host = f"db.{project_ref}.supabase.co"
        candidates.append(
            (
                "direct-db",
                f"postgresql://postgres:{quoted_pw}@{db_host}:5432/postgres?sslmode=require",
            )
        )

        # IPv4 transaction/session poolers (works on hosts without IPv6 routes).
        preferred_pooler = os.getenv("ALITTLEBITOFMONEY_SUPABASE_POOLER_HOST", "").strip()
        pooler_hosts = [
            preferred_pooler,
            "aws-0-us-west-2.pooler.supabase.com",
            "aws-0-us-east-1.pooler.supabase.com",
            "aws-0-us-east-2.pooler.supabase.com",
            "aws-0-us-west-1.pooler.supabase.com",
            "aws-0-eu-west-1.pooler.supabase.com",
            "aws-0-eu-central-1.pooler.supabase.com",
            "aws-0-ap-southeast-1.pooler.supabase.com",
            "aws-0-ap-northeast-1.pooler.supabase.com",
        ]
        pooler_user = f"postgres.{project_ref}"
        for pooler_host in pooler_hosts:
            if not pooler_host:
                continue
            for port in (6543, 5432):
                candidates.append(
                    (
                        f"pooler-{pooler_host}:{port}",
                        (
                            f"postgresql://{pooler_user}:{quoted_pw}"
                            f"@{pooler_host}:{port}/postgres?sslmode=require"
                        ),
                    )
                )

        deduped: list[tuple[str, str]] = []
        seen = set()
        for name, dsn in candidates:
            if dsn in seen:
                continue
            seen.add(dsn)
            deduped.append((name, dsn))
        return deduped
