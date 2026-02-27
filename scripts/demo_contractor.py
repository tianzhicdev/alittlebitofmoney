#!/usr/bin/env python3
"""
AI for Hire demo — CONTRACTOR side.

Usage:
    CONTRACTOR_TOKEN=abl_... python3 scripts/demo_contractor.py [BASE_URL]

Lifecycle:
  1. Check balance (GET /api/v1/ai-for-hire/me)
  2. Browse open tasks (GET /api/v1/ai-for-hire/tasks?status=open)
  3. Pick first task, submit quote (POST .../quotes)
  4. Poll for quote acceptance (GET /api/v1/ai-for-hire/tasks/{id})
  5. Read buyer messages (GET .../quotes/{qid}/messages)
  6. Deliver work (POST .../deliver)
  7. Poll for task completion (GET /api/v1/ai-for-hire/tasks/{id})
  8. Check final balance
"""

import base64
import json
import os
import sys
import time

import requests

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else os.getenv("BASE_URL", "https://alittlebitofmoney.com")
TOKEN = os.environ["CONTRACTOR_TOKEN"]
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
    print("=== CONTRACTOR DEMO ===\n")

    # 1. Check balance
    print("[1] Checking balance...")
    status, me = api("GET", "/api/v1/ai-for-hire/me")
    assert status == 200, f"Expected 200, got {status}"
    initial_balance = me["balance_sats"]
    print(f"    Account: {me['account_id']}, Balance: {initial_balance} sats\n")

    # 2. Browse open tasks
    print("[2] Browsing open tasks...")
    deadline = time.time() + POLL_TIMEOUT
    tasks = []
    while time.time() < deadline:
        status, data = api("GET", "/api/v1/ai-for-hire/tasks?status=open")
        tasks = data.get("tasks", [])
        if tasks:
            print(f"    Found {len(tasks)} open task(s)!\n")
            break
        print(f"    No open tasks yet, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
    else:
        print("    TIMEOUT waiting for open tasks.")
        sys.exit(1)

    # Pick first task
    task = tasks[0]
    task_id = task["id"]
    print(f"    Task: \"{task['title']}\" (budget {task['budget_sats']} sats)\n")

    # 3. Submit quote
    quote_price = min(task["budget_sats"], 300)
    print(f"[3] Submitting quote for {quote_price} sats...")
    status, quote = api("POST", f"/api/v1/ai-for-hire/tasks/{task_id}/quotes", {
        "price_sats": quote_price,
        "description": "I'll write a great haiku about Bitcoin and Lightning.",
    })
    assert status == 201, f"Expected 201, got {status}"
    quote_id = quote["id"]
    print()

    # 4. Poll for acceptance
    print("[4] Polling for quote acceptance...")
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        status, detail = api("GET", f"/api/v1/ai-for-hire/tasks/{task_id}")
        if detail.get("status") == "in_escrow":
            print(f"    Quote accepted! Task is in escrow.\n")
            break
        print(f"    Status: {detail['status']}, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
    else:
        print("    TIMEOUT waiting for quote acceptance.")
        sys.exit(1)

    # 5. Read messages on quote thread
    print("[5] Checking messages on quote thread...")
    status, msg_data = api("GET", f"/api/v1/ai-for-hire/tasks/{task_id}/quotes/{quote_id}/messages")
    messages = msg_data.get("messages", [])
    for m in messages:
        print(f"    [{m['sender_account_id'][:8]}...]: {m['body']}")
    print()

    # 6. Deliver work
    haiku = "Satoshis cascade\nThrough lightning channels they flow\nFreedom bit by bit"
    content_b64 = base64.b64encode(haiku.encode()).decode()
    print("[6] Delivering work...")
    status, delivery = api("POST", f"/api/v1/ai-for-hire/tasks/{task_id}/deliver", {
        "filename": "haiku.txt",
        "content_base64": content_b64,
        "notes": "Here is your Bitcoin haiku with a lightning reference!",
    })
    assert status == 201, f"Expected 201, got {status}"
    print()

    # 7. Poll for completion
    print("[7] Polling for task completion...")
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        status, detail = api("GET", f"/api/v1/ai-for-hire/tasks/{task_id}")
        if detail.get("status") == "completed":
            print(f"    Task completed! Payment released.\n")
            break
        print(f"    Status: {detail['status']}, waiting {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)
    else:
        print("    TIMEOUT waiting for completion.")
        sys.exit(1)

    # 8. Check final balance
    print("[8] Final balance check...")
    status, me = api("GET", "/api/v1/ai-for-hire/me")
    final_balance = me["balance_sats"]
    earned = final_balance - initial_balance
    print(f"    Balance: {final_balance} sats (earned {earned} sats)\n")

    print("=== CONTRACTOR DEMO COMPLETE ===")


if __name__ == "__main__":
    main()
