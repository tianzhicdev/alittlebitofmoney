from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import asyncpg


class HireError(Exception):
    pass


class HireNotFound(HireError):
    pass


class HireForbidden(HireError):
    pass


class HireInvalidState(HireError):
    pass


class HireInsufficientBalance(HireError):
    def __init__(self, balance_sats: int, required_sats: int) -> None:
        super().__init__("insufficient balance")
        self.balance_sats = balance_sats
        self.required_sats = required_sats


@dataclass
class TaskRow:
    id: str
    buyer_account_id: str
    title: str
    description: str
    budget_sats: int
    status: str
    created_at: str
    updated_at: str
    quote_count: int = 0
    quotes: List[Dict[str, Any]] = field(default_factory=list)
    deliveries: List[Dict[str, Any]] = field(default_factory=list)


class HireStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                create table if not exists hire_tasks (
                  id uuid primary key,
                  buyer_account_id uuid not null references accounts(id),
                  title text not null,
                  description text not null default '',
                  budget_sats bigint not null check (budget_sats > 0),
                  status text not null default 'open'
                    check (status in ('open','in_escrow','delivered','completed','cancelled')),
                  created_at timestamptz not null default now(),
                  updated_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                """
                create table if not exists hire_quotes (
                  id uuid primary key,
                  task_id uuid not null references hire_tasks(id),
                  contractor_account_id uuid not null references accounts(id),
                  price_sats bigint not null check (price_sats > 0),
                  description text not null default '',
                  status text not null default 'pending'
                    check (status in ('pending','accepted','rejected')),
                  created_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                """
                create table if not exists hire_messages (
                  id bigserial primary key,
                  task_id uuid not null references hire_tasks(id),
                  quote_id uuid not null references hire_quotes(id),
                  sender_account_id uuid not null references accounts(id),
                  body text not null,
                  created_at timestamptz not null default now()
                );
                """
            )
            # Migrate: add quote_id column if missing (legacy rows deleted)
            has_quote_id = await conn.fetchval(
                """
                select exists (
                  select 1 from information_schema.columns
                  where table_name = 'hire_messages' and column_name = 'quote_id'
                )
                """
            )
            if not has_quote_id:
                await conn.execute("delete from hire_messages")
                await conn.execute(
                    "alter table hire_messages add column quote_id uuid not null references hire_quotes(id)"
                )
            # Migrate: add updated_at to hire_quotes if missing
            has_updated_at = await conn.fetchval(
                """
                select exists (
                  select 1 from information_schema.columns
                  where table_name = 'hire_quotes' and column_name = 'updated_at'
                )
                """
            )
            if not has_updated_at:
                await conn.execute(
                    "alter table hire_quotes add column updated_at timestamptz not null default now()"
                )
            await conn.execute(
                """
                create table if not exists hire_deliveries (
                  id uuid primary key,
                  task_id uuid not null references hire_tasks(id),
                  quote_id uuid not null references hire_quotes(id),
                  contractor_account_id uuid not null references accounts(id),
                  filename text not null default '',
                  content_base64 text not null default '',
                  notes text not null default '',
                  created_at timestamptz not null default now()
                );
                """
            )
            await conn.execute(
                "create index if not exists idx_hire_tasks_status on hire_tasks (status);"
            )
            await conn.execute(
                "create index if not exists idx_hire_quotes_task on hire_quotes (task_id);"
            )
            await conn.execute(
                "create index if not exists idx_hire_messages_quote on hire_messages (quote_id, id);"
            )

    # -- account info ----------------------------------------------------------

    async def get_account_info(self, account_id: str) -> Dict[str, Any]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "select id, balance_sats from accounts where id = $1",
                uuid.UUID(account_id),
            )
        if row is None:
            raise HireNotFound("account not found")
        return {"account_id": str(row["id"]), "balance_sats": int(row["balance_sats"])}

    # -- tasks -----------------------------------------------------------------

    async def create_task(
        self,
        buyer_account_id: str,
        title: str,
        description: str,
        budget_sats: int,
    ) -> Dict[str, Any]:
        task_id = uuid.uuid4()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into hire_tasks (id, buyer_account_id, title, description, budget_sats)
                values ($1, $2, $3, $4, $5)
                returning id, buyer_account_id, title, description, budget_sats, status,
                          created_at, updated_at
                """,
                task_id,
                uuid.UUID(buyer_account_id),
                title,
                description,
                budget_sats,
            )
        return self._task_row_to_dict(row)

    async def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    """
                    select t.*, coalesce(q.cnt, 0) as quote_count
                    from hire_tasks t
                    left join (
                      select task_id, count(*) as cnt from hire_quotes group by task_id
                    ) q on q.task_id = t.id
                    where t.status = $1
                    order by t.created_at desc
                    """,
                    status,
                )
            else:
                rows = await conn.fetch(
                    """
                    select t.*, coalesce(q.cnt, 0) as quote_count
                    from hire_tasks t
                    left join (
                      select task_id, count(*) as cnt from hire_quotes group by task_id
                    ) q on q.task_id = t.id
                    order by t.created_at desc
                    """,
                )
        return [self._task_row_to_dict(r, quote_count=int(r["quote_count"])) for r in rows]

    async def get_task_detail(self, task_id: str) -> Dict[str, Any]:
        uid = uuid.UUID(task_id)
        async with self._pool.acquire() as conn:
            task_row = await conn.fetchrow(
                "select * from hire_tasks where id = $1", uid
            )
            if task_row is None:
                raise HireNotFound("task not found")

            quote_rows = await conn.fetch(
                """
                select q.id, q.task_id, q.contractor_account_id, q.price_sats,
                       q.description, q.status, q.created_at, q.updated_at,
                       coalesce(m.cnt, 0) as message_count
                from hire_quotes q
                left join (
                  select quote_id, count(*) as cnt from hire_messages group by quote_id
                ) m on m.quote_id = q.id
                where q.task_id = $1
                order by q.created_at
                """,
                uid,
            )
            del_rows = await conn.fetch(
                """
                select id, task_id, quote_id, contractor_account_id, filename, notes, created_at
                from hire_deliveries where task_id = $1 order by created_at
                """,
                uid,
            )

        result = self._task_row_to_dict(task_row, quote_count=len(quote_rows))
        result["quotes"] = [self._record_to_dict(r) for r in quote_rows]
        result["deliveries"] = [self._record_to_dict(r) for r in del_rows]
        return result

    # -- quotes ----------------------------------------------------------------

    async def create_quote(
        self,
        task_id: str,
        contractor_account_id: str,
        price_sats: int,
        description: str,
    ) -> Dict[str, Any]:
        quote_id = uuid.uuid4()
        uid_task = uuid.UUID(task_id)
        uid_contractor = uuid.UUID(contractor_account_id)
        async with self._pool.acquire() as conn:
            task_row = await conn.fetchrow(
                "select status, buyer_account_id from hire_tasks where id = $1",
                uid_task,
            )
            if task_row is None:
                raise HireNotFound("task not found")
            if task_row["status"] != "open":
                raise HireInvalidState("task is not open for quotes")
            if str(task_row["buyer_account_id"]) == contractor_account_id:
                raise HireForbidden("cannot quote on your own task")

            row = await conn.fetchrow(
                """
                insert into hire_quotes (id, task_id, contractor_account_id, price_sats, description)
                values ($1, $2, $3, $4, $5)
                returning id, task_id, contractor_account_id, price_sats, description, status, created_at, updated_at
                """,
                quote_id,
                uid_task,
                uid_contractor,
                price_sats,
                description,
            )
        return self._record_to_dict(row)

    async def accept_quote(
        self,
        task_id: str,
        quote_id: str,
        caller_account_id: str,
        skip_debit: bool = False,
    ) -> Dict[str, Any]:
        """
        Accept a quote — atomic escrow lock.

        When *skip_debit* is False (Bearer flow), the buyer's balance is debited.
        When *skip_debit* is True (L402 flow), the Lightning payment already
        covers the escrow — balance is not touched.
        """
        uid_task = uuid.UUID(task_id)
        uid_quote = uuid.UUID(quote_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # Lock the task row
                task_row = await conn.fetchrow(
                    "select * from hire_tasks where id = $1 for update",
                    uid_task,
                )
                if task_row is None:
                    raise HireNotFound("task not found")
                if task_row["status"] != "open":
                    raise HireInvalidState("task is not open")
                if str(task_row["buyer_account_id"]) != caller_account_id:
                    raise HireForbidden("only the buyer can accept quotes")

                # Get the quote
                quote_row = await conn.fetchrow(
                    "select * from hire_quotes where id = $1 and task_id = $2 for update",
                    uid_quote,
                    uid_task,
                )
                if quote_row is None:
                    raise HireNotFound("quote not found")
                if quote_row["status"] != "pending":
                    raise HireInvalidState("quote is not pending")

                price = int(quote_row["price_sats"])

                if not skip_debit:
                    # Bearer flow: lock buyer account and check balance
                    buyer_row = await conn.fetchrow(
                        "select id, balance_sats from accounts where id = $1 for update",
                        uuid.UUID(caller_account_id),
                    )
                    if buyer_row is None:
                        raise HireNotFound("buyer account not found")
                    balance = int(buyer_row["balance_sats"])
                    if balance < price:
                        raise HireInsufficientBalance(balance_sats=balance, required_sats=price)

                    # Debit buyer
                    await conn.execute(
                        "update accounts set balance_sats = balance_sats - $1, updated_at = now() where id = $2",
                        price,
                        uuid.UUID(caller_account_id),
                    )

                # Log the escrow (debit or L402-funded)
                await conn.execute(
                    "insert into usage_log (account_id, endpoint, amount_sats) values ($1, $2, $3)",
                    uuid.UUID(caller_account_id),
                    f"hire:escrow_lock:{task_id}",
                    price,
                )

                # Accept this quote, reject others
                await conn.execute(
                    "update hire_quotes set status = 'accepted' where id = $1",
                    uid_quote,
                )
                await conn.execute(
                    "update hire_quotes set status = 'rejected' where task_id = $1 and id != $2 and status = 'pending'",
                    uid_task,
                    uid_quote,
                )

                # Move task to in_escrow
                await conn.execute(
                    "update hire_tasks set status = 'in_escrow', updated_at = now() where id = $1",
                    uid_task,
                )

        return {"task_id": task_id, "quote_id": quote_id, "status": "in_escrow", "escrowed_sats": price}

    # -- account debit/credit (for collect endpoint) ---------------------------

    async def debit_account(
        self, account_id: str, amount_sats: int, endpoint: str,
    ) -> None:
        """Debit an account by account_id (not token). Raises HireInsufficientBalance."""
        uid = uuid.UUID(account_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "select id, balance_sats from accounts where id = $1 for update", uid,
                )
                if row is None:
                    raise HireNotFound("account not found")
                balance = int(row["balance_sats"])
                if balance < amount_sats:
                    raise HireInsufficientBalance(balance_sats=balance, required_sats=amount_sats)
                await conn.execute(
                    "update accounts set balance_sats = balance_sats - $1, updated_at = now() where id = $2",
                    amount_sats, uid,
                )
                await conn.execute(
                    "insert into usage_log (account_id, endpoint, amount_sats) values ($1, $2, $3)",
                    uid, endpoint, amount_sats,
                )

    async def credit_account(self, account_id: str, amount_sats: int) -> None:
        """Credit an account (e.g. refund on failed LN payment)."""
        uid = uuid.UUID(account_id)
        async with self._pool.acquire() as conn:
            await conn.execute(
                "update accounts set balance_sats = balance_sats + $1, updated_at = now() where id = $2",
                amount_sats, uid,
            )

    # -- quote-scoped messages -------------------------------------------------

    async def send_quote_message(
        self, task_id: str, quote_id: str, sender_account_id: str, body: str
    ) -> Dict[str, Any]:
        uid_task = uuid.UUID(task_id)
        uid_quote = uuid.UUID(quote_id)
        uid_sender = uuid.UUID(sender_account_id)
        async with self._pool.acquire() as conn:
            task_row = await conn.fetchrow(
                "select buyer_account_id from hire_tasks where id = $1", uid_task
            )
            if task_row is None:
                raise HireNotFound("task not found")
            quote_row = await conn.fetchrow(
                "select contractor_account_id, status from hire_quotes where id = $1 and task_id = $2",
                uid_quote, uid_task,
            )
            if quote_row is None:
                raise HireNotFound("quote not found")
            if quote_row["status"] not in ("pending", "accepted"):
                raise HireInvalidState("cannot message on a rejected quote")
            buyer_id = str(task_row["buyer_account_id"])
            contractor_id = str(quote_row["contractor_account_id"])
            if sender_account_id not in (buyer_id, contractor_id):
                raise HireForbidden("only the buyer or contractor can message this quote")
            row = await conn.fetchrow(
                """
                insert into hire_messages (task_id, quote_id, sender_account_id, body)
                values ($1, $2, $3, $4)
                returning id, task_id, quote_id, sender_account_id, body, created_at
                """,
                uid_task, uid_quote, uid_sender, body,
            )
        return self._record_to_dict(row)

    async def get_quote_messages(
        self, task_id: str, quote_id: str, caller_account_id: str, since_id: int = 0
    ) -> List[Dict[str, Any]]:
        uid_task = uuid.UUID(task_id)
        uid_quote = uuid.UUID(quote_id)
        async with self._pool.acquire() as conn:
            task_row = await conn.fetchrow(
                "select buyer_account_id from hire_tasks where id = $1", uid_task
            )
            if task_row is None:
                raise HireNotFound("task not found")
            quote_row = await conn.fetchrow(
                "select contractor_account_id from hire_quotes where id = $1 and task_id = $2",
                uid_quote, uid_task,
            )
            if quote_row is None:
                raise HireNotFound("quote not found")
            buyer_id = str(task_row["buyer_account_id"])
            contractor_id = str(quote_row["contractor_account_id"])
            if caller_account_id not in (buyer_id, contractor_id):
                raise HireForbidden("only the buyer or contractor can read this quote's messages")
            rows = await conn.fetch(
                """
                select id, task_id, quote_id, sender_account_id, body, created_at
                from hire_messages
                where quote_id = $1 and id > $2
                order by id
                """,
                uid_quote, since_id,
            )
        return [self._record_to_dict(r) for r in rows]

    # -- quote updates ---------------------------------------------------------

    async def update_quote(
        self, task_id: str, quote_id: str, caller_account_id: str,
        price_sats: Optional[int] = None, description: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid_task = uuid.UUID(task_id)
        uid_quote = uuid.UUID(quote_id)
        async with self._pool.acquire() as conn:
            quote_row = await conn.fetchrow(
                "select * from hire_quotes where id = $1 and task_id = $2",
                uid_quote, uid_task,
            )
            if quote_row is None:
                raise HireNotFound("quote not found")
            if str(quote_row["contractor_account_id"]) != caller_account_id:
                raise HireForbidden("only the contractor can update their quote")
            if quote_row["status"] != "pending":
                raise HireInvalidState("can only update pending quotes")
            sets = []
            vals: list = []
            idx = 1
            if price_sats is not None:
                if price_sats <= 0:
                    raise HireError("price_sats must be positive")
                sets.append(f"price_sats = ${idx}")
                vals.append(price_sats)
                idx += 1
            if description is not None:
                sets.append(f"description = ${idx}")
                vals.append(description)
                idx += 1
            if not sets:
                raise HireError("nothing to update")
            sets.append(f"updated_at = now()")
            vals.append(uid_quote)
            sql = f"update hire_quotes set {', '.join(sets)} where id = ${idx} returning id, task_id, contractor_account_id, price_sats, description, status, created_at, updated_at"
            row = await conn.fetchrow(sql, *vals)
        return self._record_to_dict(row)

    # -- deliveries ------------------------------------------------------------

    async def create_delivery(
        self,
        task_id: str,
        contractor_account_id: str,
        filename: str,
        content_base64: str,
        notes: str,
    ) -> Dict[str, Any]:
        uid_task = uuid.UUID(task_id)
        uid_contractor = uuid.UUID(contractor_account_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                task_row = await conn.fetchrow(
                    "select * from hire_tasks where id = $1 for update",
                    uid_task,
                )
                if task_row is None:
                    raise HireNotFound("task not found")
                if task_row["status"] != "in_escrow":
                    raise HireInvalidState("task is not in escrow")

                # Find the accepted quote for this contractor
                quote_row = await conn.fetchrow(
                    """
                    select id from hire_quotes
                    where task_id = $1 and contractor_account_id = $2 and status = 'accepted'
                    """,
                    uid_task,
                    uid_contractor,
                )
                if quote_row is None:
                    raise HireForbidden("no accepted quote for this contractor")

                delivery_id = uuid.uuid4()
                row = await conn.fetchrow(
                    """
                    insert into hire_deliveries
                      (id, task_id, quote_id, contractor_account_id, filename, content_base64, notes)
                    values ($1, $2, $3, $4, $5, $6, $7)
                    returning id, task_id, quote_id, contractor_account_id, filename, notes, created_at
                    """,
                    delivery_id,
                    uid_task,
                    quote_row["id"],
                    uid_contractor,
                    filename,
                    content_base64,
                    notes,
                )

                # Move task to delivered
                await conn.execute(
                    "update hire_tasks set status = 'delivered', updated_at = now() where id = $1",
                    uid_task,
                )

        return self._record_to_dict(row)

    # -- confirm (release escrow) ----------------------------------------------

    async def confirm_delivery(
        self, task_id: str, caller_account_id: str
    ) -> Dict[str, Any]:
        """Confirm delivery — atomic escrow release: credit contractor."""
        uid_task = uuid.UUID(task_id)
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                task_row = await conn.fetchrow(
                    "select * from hire_tasks where id = $1 for update",
                    uid_task,
                )
                if task_row is None:
                    raise HireNotFound("task not found")
                if task_row["status"] != "delivered":
                    raise HireInvalidState("task is not in delivered state")
                if str(task_row["buyer_account_id"]) != caller_account_id:
                    raise HireForbidden("only the buyer can confirm delivery")

                # Find accepted quote to get contractor + price
                quote_row = await conn.fetchrow(
                    "select * from hire_quotes where task_id = $1 and status = 'accepted'",
                    uid_task,
                )
                if quote_row is None:
                    raise HireInvalidState("no accepted quote found")

                price = int(quote_row["price_sats"])
                contractor_id = quote_row["contractor_account_id"]

                # Credit contractor
                await conn.execute(
                    "update accounts set balance_sats = balance_sats + $1, updated_at = now() where id = $2",
                    price,
                    contractor_id,
                )

                # Log the escrow release
                await conn.execute(
                    "insert into usage_log (account_id, endpoint, amount_sats) values ($1, $2, $3)",
                    contractor_id,
                    f"hire:escrow_release:{task_id}",
                    price,
                )

                # Mark task completed
                await conn.execute(
                    "update hire_tasks set status = 'completed', updated_at = now() where id = $1",
                    uid_task,
                )

        return {
            "task_id": task_id,
            "status": "completed",
            "released_sats": price,
            "contractor_account_id": str(contractor_id),
        }

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _task_row_to_dict(row: asyncpg.Record, quote_count: int = 0) -> Dict[str, Any]:
        return {
            "id": str(row["id"]),
            "buyer_account_id": str(row["buyer_account_id"]),
            "title": row["title"],
            "description": row["description"],
            "budget_sats": int(row["budget_sats"]),
            "status": row["status"],
            "quote_count": quote_count,
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
        }

    @staticmethod
    def _record_to_dict(row: asyncpg.Record) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        for key in row.keys():
            val = row[key]
            if isinstance(val, uuid.UUID):
                d[key] = str(val)
            elif hasattr(val, "isoformat"):
                d[key] = val.isoformat()
            else:
                d[key] = val
        return d
