import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

CALENDAR_URL = "https://museum-tickets.nintendo.com/calendar?lang=ja"
TICKET_URL = "https://museum-tickets.nintendo.com/?lang=ja"

TARGET_DATES = [
    "10月17日",
    "10月18日",
    "2026/10/17",
    "2026/10/18",
    "2026-10-17",
    "2026-10-18",
]

STATE_FILE = Path("seen.json")
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]


def notify_line(message):
    url = "https://api.line.me/v2/bot/message/broadcast"

    headers = {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }

    body = {
        "messages": [
            {
                "type": "text",
                "text": message[:5000],
            }
        ]
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=20,
    )

    response.raise_for_status()


def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def find_availability(page):
    page.goto(
        CALENDAR_URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(5000)

    body = page.locator("body").inner_text(
        timeout=15000
    )

    hits = []

    positive_words = [
        "先着順販売",
        "販売中",
        "購入",
        "空き",
        "受付中",
        "available",
        "purchase",
    ]

    negative_words = [
        "売り切れ",
        "販売終了",
        "受付終了",
        "満席",
        "sold out",
        "unavailable",
    ]

    for target in TARGET_DATES:

        start = 0

        while True:

            index = body.find(
                target,
                start,
            )

            if index == -1:
                break

            window = body[
                max(0, index - 800):
                index + 1800
            ]

            lower_window = window.lower()

            has_positive = any(
                word.lower() in lower_window
                for word in positive_words
            )

            has_negative = any(
                word.lower() in lower_window
                for word in negative_words
            )

            if has_positive and not has_negative:

                hits.append(
                    (
                        target,
                        " ".join(
                            window.split()
                        )[:1000],
                    )
                )

                break

            start = index + len(target)

    return hits


def main():

    with sync_playwright() as playwright:

        browser = playwright.chromium.launch(
            headless=True
        )

        page = browser.new_page(
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )

        hits = find_availability(page)

        browser.close()

    state = load_state()

    now = datetime.now(
        timezone(
            timedelta(hours=9)
        )
    ).isoformat(
        timespec="seconds"
    )

    if hits:

        fingerprint = hashlib.sha256(
            json.dumps(
                hits,
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

        if state.get(
            "last_alert"
        ) != fingerprint:

            message_lines = [
                "🎮 ニンテンドーミュージアム空き通知",
                "",
                "⚠️ 10/17 または 10/18 に空きの可能性があります！",
                "",
                "👥 希望人数：2名",
                "⏰ 時間：いつでも",
                "",
            ]

            for date, snippet in hits:

                message_lines.append(
                    f"📅 {date}"
                )

                message_lines.append(
                    snippet
                )

                message_lines.append("")

            message_lines.extend(
                [
                    "👇 すぐ公式サイトを確認",
                    TICKET_URL,
                ]
            )

            notify_line(
                "\n".join(message_lines)
            )

            state["last_alert"] = fingerprint

            state["last_alert_at"] = now

    state["last_check_at"] = now

    save_state(state)


if __name__ == "__main__":
    main()
