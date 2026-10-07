import os
import re
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

TICKET_URL = "https://museum-tickets.nintendo.com/ja"
TARGET_DATES = ["2026/10/17", "2026/10/18", "2026-10-17", "2026-10-18", "10月17日", "10月18日"]
STATE_FILE = Path("seen.json")

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

def notify_line(message: str):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }
    body = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": message[:5000]}],
    }
    r = requests.post(url, headers=headers, json=body, timeout=20)
    r.raise_for_status()

def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def page_has_target_availability(page):
    # First load the Japanese ticket page.
    page.goto(TICKET_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    # Some ticket UI is rendered dynamically.
    body = page.locator("body").inner_text(timeout=15000)

    # If the page is English, still inspect it.
    if "Sign In" in body and "Purchase Tickets" in body:
        pass

    # Look for target dates. We deliberately don't attempt checkout/login.
    target_found = [d for d in TARGET_DATES if d in body]
    if not target_found:
        return []

    # Generic availability markers used by the ticket UI.
    positive = [
        "購入", "予約", "空き", "販売中", "残り", "available",
        "purchase", "select", "book", "Tickets available"
    ]
    negative = [
        "売り切れ", "販売終了", "受付終了", "満席",
        "sold out", "unavailable", "closed"
    ]

    # We inspect visible text around each target date.
    hits = []
    for d in target_found:
        idx = body.find(d)
        window = body[max(0, idx-500):idx+1200]
        low = window.lower()
        has_positive = any(x.lower() in low for x in positive)
        has_negative = any(x.lower() in low for x in negative)

        # Avoid false positives where the page merely describes the ticket system.
        if has_positive and not (has_negative and not ("購入" in window or "available" in low)):
            hits.append((d, window.replace("\n", " ")[:900]))

    return hits

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="ja-JP", timezone_id="Asia/Tokyo")
        hits = page_has_target_availability(page)
        browser.close()

    state = load_state()
    now = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds")

    if hits:
        fingerprint = hashlib.sha256(
            json.dumps(hits, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()

        if state.get("last_alert") != fingerprint:
            lines = [
                "🎮 ニンテンドーミュージアムに空きの可能性！",
                "2名・希望日: 10/17 または 10/18",
                "",
            ]
            for d, snippet in hits:
                lines.append(f"📅 {d}")
                lines.append(snippet)
                lines.append("")
            lines.append("👇 公式チケットページ")
            lines.append(TICKET_URL)

            notify_line("\n".join(lines))
            state["last_alert"] = fingerprint
            state["last_alert_at"] = now

    state["last_check_at"] = now
    save_state(state)

if __name__ == "__main__":
    main()
