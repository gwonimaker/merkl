#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any


HYPERLIQUID_DEX = os.getenv("HYPERLIQUID_DEX", "xyz")
HYPERLIQUID_COIN = os.getenv("HYPERLIQUID_COIN", "xyz:SKHX")
KRX_SYMBOL = os.getenv("KRX_SYMBOL", "000660.KS")
FX_SYMBOL = os.getenv("FX_SYMBOL", "KRW=X")


def fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def fmt_krw(value: float) -> str:
    return f"₩{value:,.0f}"


def fmt_fx(value: float) -> str:
    return f"{value:,.2f}"


def fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def fmt_funding(value: float) -> str:
    return f"{value:.4f}%"


def request_json(url: str, *, data: dict[str, Any] | None = None, timeout: int = 25) -> Any:
    encoded = None
    method = "GET"
    headers = {
        "Accept": "application/json",
        "User-Agent": "gwonimaker-skhynix-gap-alert/1.0",
    }

    if data is not None:
        encoded = json.dumps(data).encode("utf-8")
        method = "POST"
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=encoded, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def hyperliquid_info(body: dict[str, Any]) -> Any:
    return request_json("https://api.hyperliquid.xyz/info", data=body)


def get_hyperliquid_market() -> dict[str, Any]:
    meta, ctxs = hyperliquid_info({"type": "metaAndAssetCtxs", "dex": HYPERLIQUID_DEX})
    universe = meta.get("universe", [])

    for idx, asset in enumerate(universe):
        if asset.get("name") == HYPERLIQUID_COIN:
            return {"coin": asset["name"], "ctx": ctxs[idx]}

    raise RuntimeError(f"Hyperliquid에서 {HYPERLIQUID_COIN} 마켓을 찾지 못했습니다.")


def yahoo_price(symbol: str) -> dict[str, float]:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded_symbol}?interval=1m&range=1d"
    payload = request_json(url)

    result = (payload.get("chart", {}).get("result") or [None])[0]
    if not result:
        raise RuntimeError(f"{symbol} 가격 응답이 비어 있습니다.")

    meta = result.get("meta", {})
    timestamps = result.get("timestamp") or []
    price = meta.get("regularMarketPrice", meta.get("previousClose"))
    time_sec = meta.get("regularMarketTime") or (timestamps[-1] if timestamps else None)

    if price in (None, ""):
        raise RuntimeError(f"{symbol} 가격을 가져오지 못했습니다.")
    if time_sec in (None, ""):
        raise RuntimeError(f"{symbol} 가격 시간을 가져오지 못했습니다.")

    return {"price": float(price), "time_ms": float(time_sec) * 1000}


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
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    request = urllib.request.Request(endpoint, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected the message: {payload}")


def build_message() -> str:
    hl = get_hyperliquid_market()
    krx = yahoo_price(KRX_SYMBOL)
    fx = yahoo_price(FX_SYMBOL)

    ctx = hl["ctx"]
    hl_price = float(ctx.get("markPx") or ctx.get("midPx") or ctx.get("oraclePx"))
    hl_mid = float(ctx["midPx"]) if ctx.get("midPx") else None
    hl_oracle = float(ctx["oraclePx"]) if ctx.get("oraclePx") else None
    funding_hourly_pct = float(ctx.get("funding") or 0) * 100

    spot_usd = krx["price"] / fx["price"]
    diff_usd = hl_price - spot_usd
    gap_pct = (diff_usd / spot_usd) * 100
    spot_age_min = round((datetime.now().timestamp() * 1000 - krx["time_ms"]) / 60000)

    now_kst = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S")
    direction = "HL 고평가" if gap_pct >= 0 else "HL 저평가"

    rows = [
        f"USD/KRW   {fmt_fx(fx['price'])}",
        f"KRX 현물   {fmt_krw(krx['price'])}",
        f"현물 USD   {fmt_usd(spot_usd)}",
        f"HL 가격    {fmt_usd(hl_price)}",
        f"갭         {fmt_pct(gap_pct)} ({direction})",
        f"차이       {fmt_usd(diff_usd)}",
        f"펀딩       {fmt_funding(funding_hourly_pct)} / h",
        f"24h 환산   {fmt_funding(funding_hourly_pct * 24)}",
    ]
    if hl_mid is not None:
        rows.append(f"HL Mid    {fmt_usd(hl_mid)}")
    if hl_oracle is not None:
        rows.append(f"HL Oracle {fmt_usd(hl_oracle)}")

    stale_note = ""
    if spot_age_min > 90:
        stale_note = (
            "\n\n<b>메모</b>\n"
            f"KRX 가격이 약 {spot_age_min}분 전 값입니다. 장마감/휴장일 수 있습니다."
        )

    return (
        "<b>📊 SK하이닉스 갭 / 펀딩</b>\n"
        f"<code>{html.escape(now_kst)} KST</code>\n\n"
        "<b>요약</b>\n"
        f"<pre>{html.escape(chr(10).join(rows))}</pre>"
        f"{stale_note}"
    )


def main() -> int:
    try:
        send_telegram(build_message())
        print("Sent SK hynix gap/funding alert.")
        return 0
    except Exception as error:
        fallback = (
            "<b>⚠️ SK하이닉스 알림 오류</b>\n\n"
            f"<pre>{html.escape(str(error))}</pre>"
        )
        try:
            send_telegram(fallback)
        except Exception:
            pass
        print(f"skhynix_gap_monitor failed: {error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
