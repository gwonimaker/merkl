#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_FILE = Path(os.getenv("EXCHANGE_STATE_FILE", "exchange_seen_events.json"))
SEND_INITIAL = os.getenv("EXCHANGE_SEND_INITIAL", "false").lower() in {"1", "true", "yes", "on"}
PAGE_SIZE = int(os.getenv("EXCHANGE_PAGE_SIZE", "50"))

KEYWORDS = tuple(
    word.lower()
    for word in os.getenv(
        "EXCHANGE_KEYWORDS",
        "earn,launchpool,launch pool,launchpad,launchx,poolx,pool x,"
        "startup,hodler,airdrop,staking,stake,subscribe,subscription,"
        "deposit to earn,deposit and earn,deposit to claim,deposit to win,when you deposit,"
        "lock,locked,lockup,soft-staking,"
        "simple earn,savings,dual investment,on-chain earn",
    ).split(",")
    if word.strip()
)

NEGATIVE_KEYWORDS = tuple(
    word.lower()
    for word in os.getenv(
        "EXCHANGE_NEGATIVE_KEYWORDS",
        "withdrawal suspended,withdrawal service,suspends,will suspend,maintenance,"
        "deposit and withdrawal,deposit & withdrawal,resuming,"
        "contract swap,ticker change,delisting,stock split,futures will launch,"
        "perpetual contract,margin will add",
    ).split(",")
    if word.strip()
)


@dataclass(frozen=True)
class Event:
    source: str
    title: str
    url: str
    category: str = ""
    published_at: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.url or self.title}".lower()


def request_text(url: str, *, accept: str = "text/html,application/json", timeout: int = 25) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "gwonimaker-exchange-telegram-alert/1.0",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def request_json(url: str, *, timeout: int = 25) -> Any:
    return json.loads(request_text(url, accept="application/json", timeout=timeout))


def matches_keywords(title: str, *, include_negative: bool = True) -> bool:
    normalized = title.lower()
    if not any(keyword_match(normalized, keyword) for keyword in KEYWORDS):
        return False
    if include_negative and any(keyword_match(normalized, keyword) for keyword in NEGATIVE_KEYWORDS):
        return False
    return True


def keyword_match(text: str, keyword: str) -> bool:
    pattern = re.escape(keyword.strip().lower())
    pattern = re.sub(r"\\\s+", r"\\s+", pattern)
    return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", text) is not None


def clean_title(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def ts_to_utc(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return str(value)
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def binance_article_url(article: dict[str, Any]) -> str:
    code = article.get("code")
    if code:
        return f"https://www.binance.com/en/support/announcement/{code}"
    return "https://www.binance.com/en/support/announcement"


def fetch_binance() -> list[Event]:
    urls = [
        f"https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize={PAGE_SIZE}",
        f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=49&pageNo=1&pageSize={PAGE_SIZE}",
        f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=93&pageNo=1&pageSize={PAGE_SIZE}",
        f"https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query?catalogId=128&pageNo=1&pageSize={PAGE_SIZE}",
    ]
    events: dict[str, Event] = {}

    for url in urls:
        payload = request_json(url)
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        articles = list(data.get("articles") or [])
        for catalog in data.get("catalogs") or []:
            articles.extend(catalog.get("articles") or [])

        for article in articles:
            if not isinstance(article, dict):
                continue
            title = clean_title(str(article.get("title") or ""))
            if not title or not matches_keywords(title):
                continue

            event = Event(
                source="Binance",
                title=title,
                url=binance_article_url(article),
                category=str(article.get("catalogName") or ""),
                published_at=ts_to_utc(article.get("releaseDate") or article.get("publishDate")),
            )
            events[event.key] = event

    return list(events.values())


def fetch_bybit() -> list[Event]:
    url = f"https://api.bybit.com/v5/announcements/index?locale=en-US&limit={PAGE_SIZE}"
    payload = request_json(url)
    items = payload.get("result", {}).get("list", []) if isinstance(payload, dict) else []
    events: list[Event] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        title = clean_title(str(item.get("title") or ""))
        if not title or not matches_keywords(title):
            continue

        category = ""
        if isinstance(item.get("type"), dict):
            category = str(item["type"].get("title") or item["type"].get("key") or "")

        events.append(
            Event(
                source="Bybit",
                title=title,
                url=str(item.get("url") or "https://announcements.bybit.com/en-US/"),
                category=category,
                published_at=ts_to_utc(item.get("publishTime") or item.get("dateTimestamp")),
            )
        )

    return events


def parse_bitget_support_page(url: str) -> list[Event]:
    body = request_text(url)
    events: dict[str, Event] = {}

    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S):
        href = html.unescape(match.group(1))
        if "/support/articles/" not in href:
            continue

        title = clean_title(match.group(2))
        if not title or not matches_keywords(title):
            continue
        if title.lower().startswith(("what is ", "how to ")):
            continue

        if href.startswith("/"):
            href = "https://www.bitget.com" + href

        event = Event(source="Bitget", title=title, url=href, category="Support")
        events[event.key] = event

    return list(events.values())


def fetch_bitget() -> list[Event]:
    urls = [
        "https://www.bitget.com/support/categories/11865590960877",
        "https://www.bitget.com/support/categories/11865590960902",
    ]
    events: dict[str, Event] = {}
    for url in urls:
        for event in parse_bitget_support_page(url):
            events[event.key] = event
    return list(events.values())


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


def message_for(event: Event) -> str:
    title = html.escape(event.title)
    url = html.escape(event.url, quote=True)
    lines = [
        "🟡 <b>거래소 예치 이벤트 발견</b>",
        f"🏦 거래소: <b>{html.escape(event.source)}</b>",
        "",
        f"📌 <b>{title}</b>",
    ]
    if event.category:
        lines.append(f"🧭 분류: {html.escape(event.category)}")
    if event.published_at:
        lines.append(f"🕒 게시: {html.escape(event.published_at)}")
    lines.extend(["", f"🔗 <a href=\"{url}\">공지 바로가기</a>"])
    return "\n".join(lines)


def collect_events() -> list[Event]:
    fetchers = [
        ("Binance", fetch_binance),
        ("Bybit", fetch_bybit),
        ("Bitget", fetch_bitget),
    ]
    events: dict[str, Event] = {}
    failures: list[str] = []

    for name, fetcher in fetchers:
        try:
            fetched = fetcher()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as error:
            failures.append(f"{name}: {error}")
            continue

        print(f"{name}: found {len(fetched)} matching event(s).")
        for event in fetched:
            events[event.key] = event

    if failures:
        print("Some sources failed:")
        for failure in failures:
            print(f"- {failure}")

    return list(events.values())


def main() -> int:
    events = collect_events()
    current_keys = {event.key for event in events}
    state = load_state()
    seen = {str(value) for value in state.get("seen", [])}
    first_run = not STATE_FILE.exists()

    if first_run and not SEND_INITIAL:
        save_state(current_keys)
        print(f"Primed {len(current_keys)} exchange events. No Telegram messages sent.")
        return 0

    new_events = [event for event in events if event.key not in seen]
    if not new_events:
        save_state(seen | current_keys)
        print(f"No new exchange events. Checked {len(events)} matching event(s).")
        return 0

    for event in new_events:
        send_telegram(message_for(event))
        time.sleep(0.25)

    save_state(seen | current_keys)
    print(f"Sent {len(new_events)} new exchange event notification(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"exchange_monitor failed: {error}", file=sys.stderr)
        raise
