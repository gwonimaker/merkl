#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


API_URL = os.getenv("MERKL_API_URL", "https://api.merkl.xyz/v4/opportunities")
STATUS = os.getenv("MERKL_STATUS", "LIVE")
PAGE_SIZE = int(os.getenv("MERKL_PAGE_SIZE", "100"))
MAX_PAGES = int(os.getenv("MERKL_MAX_PAGES", "10"))
STATE_FILE = Path(os.getenv("MERKL_STATE_FILE", "merkl_seen_opportunities.json"))
SEND_INITIAL = os.getenv("MERKL_SEND_INITIAL", "false").lower() in {"1", "true", "yes", "on"}


def request_json(url: str, *, timeout: int = 25) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "gwonimaker-merkl-telegram-alert/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def api_url_for_page(page: int) -> str:
    parsed = urllib.parse.urlparse(API_URL)
    params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    params["items"] = str(PAGE_SIZE)
    params["page"] = str(page)
    if STATUS:
        params["status"] = STATUS

    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(params))
    )


def fetch_opportunities() -> list[dict[str, Any]]:
    opportunities: list[dict[str, Any]] = []

    for page in range(MAX_PAGES):
        payload = request_json(api_url_for_page(page))
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected Merkl API response type: {type(payload).__name__}")

        opportunities.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < PAGE_SIZE:
            break

    if STATUS:
        opportunities = [
            item for item in opportunities if str(item.get("status", "")).upper() == STATUS.upper()
        ]

    return opportunities


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"seen": []}

    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"seen": []}

    if not isinstance(state, dict):
        return {"seen": []}
    if not isinstance(state.get("seen"), list):
        state["seen"] = []
    return state


def save_state(seen: set[str]) -> None:
    payload = {
        "seen": sorted(seen),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    STATE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def opportunity_id(item: dict[str, Any]) -> str:
    for key in ("id", "identifier", "opportunityId"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return json.dumps(item, sort_keys=True, ensure_ascii=True)


def amount(value: Any, suffix: str = "") -> str:
    if value in (None, ""):
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B{suffix}"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M{suffix}"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.2f}K{suffix}"
    return f"{number:.2f}{suffix}"


def campaign_end(item: dict[str, Any]) -> str | None:
    raw = item.get("latestCampaignEnd") or item.get("earliestCampaignEnd")
    if raw in (None, ""):
        return None

    try:
        timestamp = float(raw)
    except (TypeError, ValueError):
        return str(raw)

    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def opportunity_url(item: dict[str, Any]) -> str:
    if item.get("url"):
        return str(item["url"])

    item_id = item.get("id") or item.get("identifier")
    if item_id:
        return f"https://app.merkl.xyz/opportunities/{item_id}"

    return "https://app.merkl.xyz/"


def message_for(item: dict[str, Any]) -> str:
    name = html.escape(str(item.get("name") or "이름 없는 Opportunity"))
    url = html.escape(opportunity_url(item), quote=True)
    lines = [
        "🟢 <b>Merkl 새 Opportunity 발견</b>",
        f"📌 <b>{name}</b>",
        "",
        f"🏷️ 유형: <code>{html.escape(str(item.get('type', 'n/a')))}</code>",
        f"⛓️ 체인 ID: <code>{html.escape(str(item.get('chainId', 'n/a')))}</code>",
        f"📈 APR: <b>{html.escape(amount(item.get('apr'), '%'))}</b>",
        f"📊 총 APR: <b>{html.escape(amount(item.get('totalApr'), '%'))}</b>",
        f"🎁 일일 보상: <b>{html.escape(amount(item.get('dailyRewards')))}</b>",
        f"💰 TVL: <b>{html.escape(amount(item.get('tvl')))}</b>",
    ]

    end = campaign_end(item)
    if end:
        lines.append(f"⏰ 종료: {html.escape(end)}")

    tags = item.get("tags")
    if isinstance(tags, list) and tags:
        tag_text = ", ".join(str(tag) for tag in tags[:5])
        lines.append(f"🔖 태그: {html.escape(tag_text)}")

    lines.extend(["", f"🔗 <a href=\"{url}\">Merkl에서 보기</a>"])
    return "\n".join(lines)


def send_telegram(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set as GitHub Secrets.")

    endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")

    request = urllib.request.Request(endpoint, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected the message: {payload}")


def main() -> int:
    opportunities = fetch_opportunities()
    current_ids = {opportunity_id(item) for item in opportunities}

    state = load_state()
    seen = {str(value) for value in state.get("seen", [])}
    first_run = not STATE_FILE.exists()

    if first_run and not SEND_INITIAL:
        save_state(current_ids)
        print(f"Primed {len(current_ids)} current Merkl opportunities. No Telegram messages sent.")
        return 0

    new_items = [item for item in opportunities if opportunity_id(item) not in seen]

    if not new_items:
        print(f"No new Merkl opportunities. Checked {len(opportunities)} live items.")
        return 0

    for item in new_items:
        send_telegram(message_for(item))
        time.sleep(0.25)

    save_state(seen | current_ids)
    print(f"Sent {len(new_items)} new Merkl opportunity notification(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"merkl_monitor failed: {error}", file=sys.stderr)
        raise
