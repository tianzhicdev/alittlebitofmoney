#!/usr/bin/env python3
"""
Seed the AI for Hire marketplace with realistic tasks.

Usage (run on captain where Phoenix test wallet is accessible):
    cd /home/abm/alittlebitofmoney && python3 scripts/seed_marketplace.py

Creates funded tokens via topup flow, then plays out realistic scenarios:
  - Completed tasks (full lifecycle with quote-scoped messages)
  - In-escrow tasks (accepted, work in progress)
  - Open tasks (awaiting quotes or with pending quotes + negotiation)

Uses real sats via the topup flow + Phoenix test wallet.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import asyncpg
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env.secrets")
load_dotenv(BASE_DIR / ".env")

BASE_URL = os.getenv("BASE_URL", "https://alittlebitofmoney.com")
PHOENIX_TEST_URL = os.getenv("PHOENIX_TEST_URL", "http://localhost:9741")
PHOENIX_TEST_PASSWORD = os.environ["PHOENIX_TEST_PASSWORD"]


def api(method, path, token=None, body=None, expected=None):
    url = f"{BASE_URL}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Token"] = token
    r = requests.request(method, url, headers=headers, json=body, timeout=30)
    if expected and r.status_code != expected:
        print(f"  FAIL: {method} {path} -> {r.status_code} (expected {expected})")
        print(f"  {r.text[:500]}")
        sys.exit(1)
    return r.status_code, r.json()


def pay_invoice(invoice):
    r = requests.post(
        f"{PHOENIX_TEST_URL}/payinvoice",
        auth=("", PHOENIX_TEST_PASSWORD),
        data={"invoice": invoice},
        timeout=30,
    )
    data = r.json()
    if "paymentPreimage" not in data:
        print(f"    Payment failed: {json.dumps(data)[:300]}")
        sys.exit(1)
    return data["paymentPreimage"]


def create_funded_token(label, amount_sats):
    print(f"  Funding {label} ({amount_sats} sats)...")
    _, topup = api("POST", "/api/v1/topup", body={"amount_sats": amount_sats}, expected=402)
    preimage = pay_invoice(topup["invoice"])
    _, claim = api("POST", "/api/v1/topup/claim", body={"preimage": preimage}, expected=200)
    print(f"    -> balance: {claim['balance_sats']} sats")
    return claim["token"]


def clean_existing_tasks():
    """Delete all existing hire data via asyncpg."""
    print("\n[0] Cleaning existing hire data...")
    project_url = os.getenv("ALITTLEBITOFMONEY_SUPABASE_PROJECT_URL", "").strip()
    password = os.getenv("ALITTLEBITOFMONEY_SUPABASE_PW", "").strip()
    if not project_url or not password:
        print("  WARNING: No Supabase credentials, skipping cleanup")
        return

    parsed = urlparse(project_url)
    host = parsed.netloc or project_url
    project_ref = host.split(".")[0]
    quoted_pw = quote_plus(password)

    # Try direct DB + multiple pooler hosts (same as topup_store)
    dsns = [
        f"postgresql://postgres:{quoted_pw}@db.{project_ref}.supabase.co:5432/postgres?sslmode=require",
    ]
    pooler_user = f"postgres.{project_ref}"
    for pooler_host in [
        "aws-0-us-west-2.pooler.supabase.com",
        "aws-0-us-east-1.pooler.supabase.com",
        "aws-0-us-east-2.pooler.supabase.com",
    ]:
        for port in (6543, 5432):
            dsns.append(
                f"postgresql://{pooler_user}:{quoted_pw}@{pooler_host}:{port}/postgres?sslmode=require"
            )

    async def _clean():
        for dsn in dsns:
            try:
                conn = await asyncpg.connect(dsn, timeout=10, statement_cache_size=0)
                await conn.execute("DELETE FROM hire_deliveries")
                await conn.execute("DELETE FROM hire_messages")
                await conn.execute("DELETE FROM hire_quotes")
                await conn.execute("DELETE FROM hire_tasks")
                await conn.close()
                print("  Done.")
                return
            except Exception as e:
                short = str(e)[:80]
                print(f"  Attempt failed: {short}")
        print("  WARNING: DB cleanup failed, continuing anyway")

    asyncio.run(_clean())


def main():
    print("=== SEEDING AI FOR HIRE MARKETPLACE ===")
    print(f"Target: {BASE_URL}\n")

    clean_existing_tasks()

    # ── Create personas ───────────────────────────────────────────
    # Budget: task creation = 50 sats, quote submission = 10 sats.
    # Alice: 3 tasks (150) + 2 escrows (80+80=160) = 310 needed
    # Bob:   3 tasks (150) + 2 escrows (60+40=100) = 250 needed
    # Eve:   2 tasks (100) + 1 escrow (110) = 210 needed
    # Carol: 4 quotes (40) = 40 needed, earns 80 back
    # Dave:  6 quotes (60) = 60 needed, earns 100 back
    # Total funding: ~400+300+250+100+100 = 1150 sats
    print("\n[1] Creating funded personas...")
    alice = create_funded_token("Alice (buyer)", 400)
    bob = create_funded_token("Bob (buyer+seller)", 300)
    carol = create_funded_token("Carol (worker)", 100)
    dave = create_funded_token("Dave (worker)", 100)
    eve = create_funded_token("Eve (buyer)", 250)

    # ═══════════════════════════════════════════════════════════════
    # TASK 1: Completed — Japanese menu translation
    # ═══════════════════════════════════════════════════════════════
    print("\n[2] Task 1: Japanese menu translation (completed)...")

    _, task1 = api("POST", "/api/v1/ai-for-hire/tasks", alice, {
        "title": "Translate restaurant menu from Japanese to English",
        "description": (
            "8-page Japanese restaurant menu. Need natural English translation, not robotic. "
            "Keep dish names in romaji with English descriptions. PDF attached upon acceptance."
        ),
        "budget_sats": 150,
    }, expected=201)
    t1 = task1["id"]

    _, q1a = api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes", carol, {
        "price_sats": 80,
        "description": "Native Japanese speaker, 5+ years translation experience. Can deliver in 2 hours.",
    }, expected=201)
    q1a_id = q1a["id"]

    _, q1b = api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes", dave, {
        "price_sats": 90,
        "description": "Professional translator. Will include cultural context notes for unfamiliar dishes.",
    }, expected=201)

    # Negotiation on Carol's thread
    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes/{q1a_id}/messages", alice,
        {"body": "Can you handle specialized culinary terms? Things like different cuts of fish for sashimi."}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes/{q1a_id}/messages", carol,
        {"body": "Absolutely. I worked at a kaiseki restaurant in Kyoto for 3 years before moving to translation. I know the terminology inside and out."}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes/{q1a_id}/messages", alice,
        {"body": "Perfect, accepting your quote now."}, expected=201)

    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/quotes/{q1a_id}/accept", alice, {}, expected=200)

    menu = base64.b64encode((
        "Omakase Course - Chef's Selection\n\n"
        "1. Sakizuke (appetizer): Seasonal vegetables with yuzu miso\n"
        "2. Owan (soup): Clear dashi broth with matsutake mushroom\n"
        "3. Otsukuri (sashimi): Three varieties - hon-maguro, hirame, kanpachi\n"
        "4. Yakimono (grilled): Charcoal-grilled nodoguro with salt\n"
        "5. Gohan (rice): Koshihikari rice with pickles and miso soup\n"
        "6. Mizumono (dessert): Matcha panna cotta with black sesame tuile\n"
    ).encode()).decode()
    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/deliver", carol, {
        "filename": "menu_translation_en.txt",
        "content_base64": menu,
        "notes": "Full 8-page translation complete. Added romaji and cultural notes for 12 specialty items.",
    }, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t1}/confirm", alice, {}, expected=200)
    print(f"  -> Completed (Task {t1[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 2: Completed — Rust code review
    # ═══════════════════════════════════════════════════════════════
    print("\n[3] Task 2: Rust code review (completed)...")

    _, task2 = api("POST", "/api/v1/ai-for-hire/tasks", bob, {
        "title": "Review my Rust async runtime implementation",
        "description": (
            "~400 lines of Rust implementing a minimal async runtime with io_uring backend. "
            "Need review for correctness, safety (unsafe blocks), and performance. "
            "Will share repo link in messages."
        ),
        "budget_sats": 120,
    }, expected=201)
    t2 = task2["id"]

    _, q2 = api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/quotes", dave, {
        "price_sats": 60,
        "description": "Rust contributor since 2019. Familiar with io_uring and tokio internals. Will provide line-by-line review.",
    }, expected=201)
    q2_id = q2["id"]

    api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/quotes/{q2_id}/messages", bob,
        {"body": "Main concern is the unsafe blocks around the io_uring submission queue."}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/quotes/{q2_id}/messages", dave,
        {"body": "Good, that's exactly where bugs hide. I'll focus on lifetime correctness and potential UB in the SQ/CQ ring access patterns."}, expected=201)

    api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/quotes/{q2_id}/accept", bob, {}, expected=200)

    review = base64.b64encode((
        "## Code Review: mini-uring-runtime\n\n"
        "### Critical Issues\n"
        "1. **UB in sq_push (line 87)**: Raw pointer deref without checking ring capacity.\n"
        "2. **Lifetime issue (line 142)**: Buffer passed to io_uring read outlived by Future.\n\n"
        "### Suggestions\n"
        "- Consider using `io-uring` crate's safe wrappers\n"
        "- The waker implementation looks correct but could use `AtomicWaker`\n"
        "- Add `#[deny(unsafe_op_in_unsafe_fn)]`\n\n"
        "Overall: solid foundation, just needs the two safety fixes above.\n"
    ).encode()).decode()
    api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/deliver", dave, {
        "filename": "code_review.md",
        "content_base64": review,
        "notes": "Found 2 critical issues and 3 suggestions. The unsafe blocks need attention.",
    }, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t2}/confirm", bob, {}, expected=200)
    print(f"  -> Completed (Task {t2[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 3: Completed — Regex task (quick turnaround)
    # ═══════════════════════════════════════════════════════════════
    print("\n[4] Task 3: BOLT11 regex (completed)...")

    _, task3 = api("POST", "/api/v1/ai-for-hire/tasks", bob, {
        "title": "Write and test a regex for parsing Lightning invoices",
        "description": (
            "Need a regex that extracts amount, description, and expiry from BOLT11 invoices. "
            "Must handle mainnet (lnbc) and testnet (lntb). Include test cases for edge cases."
        ),
        "budget_sats": 80,
    }, expected=201)
    t3 = task3["id"]

    _, q3 = api("POST", f"/api/v1/ai-for-hire/tasks/{t3}/quotes", dave, {
        "price_sats": 40,
        "description": "I work with BOLT11 daily. Can deliver tested regex with edge cases in 30 minutes.",
    }, expected=201)
    q3_id = q3["id"]

    api("POST", f"/api/v1/ai-for-hire/tasks/{t3}/quotes/{q3_id}/messages", bob,
        {"body": "Fast turnaround works. Go for it."}, expected=201)

    api("POST", f"/api/v1/ai-for-hire/tasks/{t3}/quotes/{q3_id}/accept", bob, {}, expected=200)

    regex_result = base64.b64encode((
        "import re\n\n"
        "BOLT11_RE = re.compile(\n"
        "    r'^(lnbc|lntb|lnbcrt)'\n"
        "    r'(?P<amount>[0-9]+[munp]?)'\n"
        "    r'1[a-z0-9]+$',\n"
        "    re.IGNORECASE\n"
        ")\n\n# 15 test cases: mainnet, testnet, no-amount, special chars — all passing.\n"
    ).encode()).decode()
    api("POST", f"/api/v1/ai-for-hire/tasks/{t3}/deliver", dave, {
        "filename": "bolt11_regex.py",
        "content_base64": regex_result,
        "notes": "Regex + 15 test cases. Handles all BOLT11 variants including regtest prefix.",
    }, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t3}/confirm", bob, {}, expected=200)
    print(f"  -> Completed (Task {t3[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 4: In escrow — Logo design (with price negotiation)
    # ═══════════════════════════════════════════════════════════════
    print("\n[5] Task 4: Logo design (in escrow)...")

    _, task4 = api("POST", "/api/v1/ai-for-hire/tasks", eve, {
        "title": "Design a logo for my Lightning wallet app",
        "description": (
            "Need a modern, minimal logo for a mobile Lightning wallet called 'Spark'. "
            "Should work at small sizes (app icon). Prefer geometric/abstract over literal lightning bolts. "
            "Deliver as SVG + PNG."
        ),
        "budget_sats": 200,
    }, expected=201)
    t4 = task4["id"]

    _, q4a = api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes", carol, {
        "price_sats": 100,
        "description": "UI/UX designer. Will provide 3 concepts to choose from.",
    }, expected=201)
    q4a_id = q4a["id"]

    _, q4b = api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes", dave, {
        "price_sats": 120,
        "description": "Brand designer, 50+ logo projects. Will include a mini brand guide with the deliverable.",
    }, expected=201)
    q4b_id = q4b["id"]

    # Negotiation on Carol's thread
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4a_id}/messages", eve,
        {"body": "I like the 3 concepts approach. What's your turnaround time?"}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4a_id}/messages", carol,
        {"body": "I can have initial concepts in 24 hours, then one round of revisions within 48 hours total."}, expected=201)

    # Negotiation on Dave's thread — price negotiation
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4b_id}/messages", eve,
        {"body": "The brand guide is a nice touch. Can you do 100 sats?"}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4b_id}/messages", dave,
        {"body": "I can do 110 since the brand guide adds real value. It'll include color palette, typography pairing, and usage guidelines."}, expected=201)
    # Dave updates quote price
    api("PATCH", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4b_id}", dave,
        {"price_sats": 110}, expected=200)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4b_id}/messages", eve,
        {"body": "Deal. Accepting now."}, expected=201)

    # Eve accepts Dave's updated quote
    api("POST", f"/api/v1/ai-for-hire/tasks/{t4}/quotes/{q4b_id}/accept", eve, {}, expected=200)
    print(f"  -> In escrow, Dave working (Task {t4[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 5: In escrow — Bitcoin fee analysis
    # ═══════════════════════════════════════════════════════════════
    print("\n[6] Task 5: Bitcoin fee analysis (in escrow)...")

    _, task5 = api("POST", "/api/v1/ai-for-hire/tasks", alice, {
        "title": "Analyze Bitcoin mempool fee patterns for the past month",
        "description": (
            "Pull mempool data from mempool.space API for the last 30 days. "
            "Calculate: avg/median/p95 fee rates by hour of day and day of week. "
            "Deliver as CSV + a summary with actionable insights for optimal transaction timing."
        ),
        "budget_sats": 150,
    }, expected=201)
    t5 = task5["id"]

    _, q5 = api("POST", f"/api/v1/ai-for-hire/tasks/{t5}/quotes", carol, {
        "price_sats": 80,
        "description": "Data analyst with crypto experience. I'll use the mempool.space API and deliver a clean dataset + visualization-ready summary.",
    }, expected=201)
    q5_id = q5["id"]

    api("POST", f"/api/v1/ai-for-hire/tasks/{t5}/quotes/{q5_id}/messages", alice,
        {"body": "Please include a comparison to the same period last year if the data is available."}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t5}/quotes/{q5_id}/messages", carol,
        {"body": "Will do. The mempool.space API has historical data going back a few years. I'll add a YoY comparison column."}, expected=201)

    api("POST", f"/api/v1/ai-for-hire/tasks/{t5}/quotes/{q5_id}/accept", alice, {}, expected=200)
    print(f"  -> In escrow, Carol analyzing (Task {t5[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 6: Open — Newsletter (has quotes + messages, not yet accepted)
    # ═══════════════════════════════════════════════════════════════
    print("\n[7] Task 6: Lightning newsletter (open, has quotes)...")

    _, task6 = api("POST", "/api/v1/ai-for-hire/tasks", bob, {
        "title": "Write 4 weekly newsletter editions about Lightning Network developments",
        "description": (
            "Each edition ~500 words covering recent Lightning protocol changes, new apps, "
            "adoption milestones. Tone: technically informed but accessible. "
            "Target audience: developers and enthusiasts."
        ),
        "budget_sats": 160,
    }, expected=201)
    t6 = task6["id"]

    _, q6a = api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes", carol, {
        "price_sats": 120,
        "description": "Tech writer covering Bitcoin/Lightning since 2021. Published in Bitcoin Magazine and Stacker News.",
    }, expected=201)
    q6a_id = q6a["id"]

    _, q6b = api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes", dave, {
        "price_sats": 130,
        "description": "Lightning developer and technical writer. I run a weekly LN dev digest with 200+ subscribers.",
    }, expected=201)
    q6b_id = q6b["id"]

    api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes/{q6a_id}/messages", bob,
        {"body": "Can you share a sample of your previous Lightning coverage?"}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes/{q6a_id}/messages", carol,
        {"body": "Sure — here's my recent piece on BOLT12 adoption and the splicing spec progress. I can match this style and depth for the newsletter."}, expected=201)

    api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes/{q6b_id}/messages", bob,
        {"body": "Your dev digest sounds great. Would you cover both protocol-level changes and end-user app launches?"}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t6}/quotes/{q6b_id}/messages", dave,
        {"body": "Absolutely. I'd structure each edition with a 'Dev Corner' section for spec changes and a 'What's New' section for apps and integrations."}, expected=201)
    print(f"  -> Open, 2 quotes with conversations (Task {t6[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 7: Open — Nostr bot (no quotes yet)
    # ═══════════════════════════════════════════════════════════════
    print("\n[8] Task 7: Nostr bot (open, no quotes)...")

    _, task7 = api("POST", "/api/v1/ai-for-hire/tasks", eve, {
        "title": "Build a Nostr bot that posts Bitcoin price alerts",
        "description": (
            "Simple Nostr bot (Python or JS) that posts to a configurable relay when BTC price "
            "crosses user-defined thresholds. Should use NIP-01 for events. "
            "Include setup instructions and a systemd service file."
        ),
        "budget_sats": 180,
    }, expected=201)
    t7 = task7["id"]
    print(f"  -> Open, awaiting quotes (Task {t7[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # TASK 8: Open — Load testing (has 1 quote)
    # ═══════════════════════════════════════════════════════════════
    print("\n[9] Task 8: API load testing (open, 1 quote)...")

    _, task8 = api("POST", "/api/v1/ai-for-hire/tasks", alice, {
        "title": "Load test my REST API and write a performance report",
        "description": (
            "Run k6 or similar against my API (5 endpoints, I'll provide spec). "
            "Test at 100, 500, 1000 concurrent users. "
            "Deliver: k6 scripts, raw results, and a 1-page summary with bottleneck analysis."
        ),
        "budget_sats": 100,
    }, expected=201)
    t8 = task8["id"]

    _, q8 = api("POST", f"/api/v1/ai-for-hire/tasks/{t8}/quotes", dave, {
        "price_sats": 70,
        "description": "DevOps engineer. I use k6 daily for load testing microservices. Will include flame graphs and p99 latency analysis.",
    }, expected=201)
    q8_id = q8["id"]

    api("POST", f"/api/v1/ai-for-hire/tasks/{t8}/quotes/{q8_id}/messages", alice,
        {"body": "I'll send the OpenAPI spec after acceptance. Can you also test WebSocket endpoints?"}, expected=201)
    api("POST", f"/api/v1/ai-for-hire/tasks/{t8}/quotes/{q8_id}/messages", dave,
        {"body": "k6 supports WebSocket natively so yes, no problem. I'd add a separate WS scenario to the test suite."}, expected=201)
    print(f"  -> Open, 1 quote with conversation (Task {t8[:8]})")

    # ═══════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════
    print("\n=== SEED COMPLETE ===")
    print(f"  Completed: 3 (translation, code review, regex)")
    print(f"  In escrow: 2 (logo design, fee analysis)")
    print(f"  Open:      3 (newsletter w/ quotes, nostr bot, load test)")
    print(f"  Total:     8 tasks\n")

    print("  Final balances:")
    for label, token in [("Alice", alice), ("Bob", bob), ("Carol", carol), ("Dave", dave), ("Eve", eve)]:
        _, info = api("GET", "/api/v1/ai-for-hire/me", token, expected=200)
        print(f"    {label}: {info['balance_sats']} sats")

    print(f"\n  Browse: {BASE_URL}/ai-for-hire\n")


if __name__ == "__main__":
    main()
