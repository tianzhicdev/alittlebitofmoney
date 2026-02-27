#!/usr/bin/env python3
"""
AI for Hire demo — BUYER side.

Usage:
    BUYER_TOKEN=abl_... python3 scripts/demo_buyer.py [BASE_URL]

Lifecycle:
  1. Check balance (GET /api/v1/ai-for-hire/me)
  2. Post a task (POST /api/v1/ai-for-hire/tasks)
  3. Poll for quotes (GET /api/v1/ai-for-hire/tasks/{id})
  4. Accept first quote (POST .../quotes/{qid}/accept)
  5. Send a message (POST .../quotes/{qid}/messages)
  6. Poll for delivery (GET /api/v1/ai-for-hire/tasks/{id})
  7. Confirm delivery (POST .../confirm)
  8. Check final balance
"""

import json
import os
import sys
import time

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.getenv("BASE_URL", "https://alittlebitofmoney.com")
TOKEN = os.environ["BUYER_TOKEN"]
HEADERS = {"X-Token": TOKEN, "Content-Type": "application/json"}
POLL_INTERVAL = 3
POLL_TIMEOUT = 120


def api(method, path, body=None):
    url = f"{BASE_URL}{path}"
    r = requests.request(method, url, headers=HEADERS, json=body, timeout=30)
    data = r.json()
    print(f"  {method} {path} → {r.status_code}")
    print(f"  {json.dumps(data, indent=2)[:500]}")
    return r.status_code, data


def main():
    print("=== BUYER DEMO ===\n")

    # 1. Check balance
    print("[1] Checking balance...")
    status, me = api("GET", "/api/v1/ai-for-hire/me")
    assert status == 200, f"Expected 200, got {status}"
    print(f"    Account: {me['account_id']}, Balance: {me['balance_sats']} sats\n")

    # 2. Post task
    print("[2] Posting task...")
    status, task = api("POST", "/api/v1/ai-for-hire/tasks", {
        "title": "Write a haiku about Bitcoin",
        "description": "Must be exactly 5-7-5 syllables. Mention lightning.",
        "budget_sats": 500,
    })
    assert status == 201, f"Expected 201, got {status}"
    task_id = task["id"]
    print(f"    Task ID: {task_id}\n")

    # 3. Poll for quotes
    print("[3] Polling for quotes...")
    deadline = time.time() + POLL_TIMEOUT
    quotes = []
    while time.time() < deadline:
        status, detail = api("GET", f"/api/v1/ai-for-hire/tasks/{task_id}")
        quotes = detail.get("quotes", [])
        if quotes:
            print(f"    Got {len(quotes)} quote(s)!\n")
            break
        print(f"    No quotes yet, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
    else:
        print("    TIMEOUT waiting for quotes.")
        sys.exit(1)

    # 4. Accept first quote
    quote = quotes[0]
    quote_id = quote["id"]
    print(f"[4] Accepting quote {quote_id} for {quote['price_sats']} sats...")
    status, result = api("POST", f"/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/accept")
    assert status == 200, f"Expected 200, got {status}"
    print(f"    Escrow locked: {result['escrowed_sats']} sats\n")

    # 5. Send message on quote thread
    print("[5] Sending message to contractor on quote thread...")
    status, msg = api("POST", f"/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/messages", {
        "body": "Looking forward to the haiku! Take your time.",
    })
    assert status == 201, f"Expected 201, got {status}"
    print()

    # 6. Poll for delivery
    print("[6] Polling for delivery...")
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        status, detail = api("GET", f"/api/v1/ai-for-hire/tasks/{task_id}")
        if detail.get("status") == "delivered":
            print(f"    Delivery received!\n")
            for d in detail.get("deliveries", []):
                print(f"    File: {d.get('filename', '(none)')}")
                print(f"    Notes: {d.get('notes', '')}\n")
            break
        print(f"    Status: {detail['status']}, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
    else:
        print("    TIMEOUT waiting for delivery.")
        sys.exit(1)

    # 7. Confirm delivery
    print("[7] Confirming delivery (releasing escrow)...")
    status, result = api("POST", f"/api/v1/ai-for-hire/tasks/{task_id}/confirm")
    assert status == 200, f"Expected 200, got {status}"
    print(f"    Released {result['released_sats']} sats to {result['contractor_account_id']}\n")

    # 8. Final balance
    print("[8] Final balance check...")
    status, me = api("GET", "/api/v1/ai-for-hire/me")
    print(f"    Balance: {me['balance_sats']} sats\n")

    print("=== BUYER DEMO COMPLETE ===")


if __name__ == "__main__":
    main()
