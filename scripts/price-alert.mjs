const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

const HYPERLIQUID_DEX = "xyz";
const HYPERLIQUID_COIN = "xyz:SKHX";
const FX_SYMBOL = process.env.FX_SYMBOL || "KRW=X";
const WTI_SYMBOL = process.env.WTI_SYMBOL || "CL=F";
const US10Y_SYMBOL = process.env.US10Y_SYMBOL || "^TNX";

if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
  throw new Error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required.");
}

const fmtUsd = (n) =>
  `$${Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const fmtFx = (n) =>
  Number(n).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

const fmtPct = (n) => `${Number(n).toFixed(2)}%`;

const escapeHtml = (s) =>
  String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");

async function sendTelegram(text) {
  const res = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: TELEGRAM_CHAT_ID,
      text,
      parse_mode: "HTML",
      disable_web_page_preview: true,
    }),
  });

  if (!res.ok) {
    throw new Error(`Telegram send failed: ${res.status} ${await res.text()}`);
  }
}

async function hlInfo(body) {
  const res = await fetch("https://api.hyperliquid.xyz/info", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) throw new Error(`Hyperliquid fetch failed: ${res.status}`);
  return await res.json();
}

async function getHynixPrice() {
  const [meta, ctxs] = await hlInfo({
    type: "metaAndAssetCtxs",
    dex: HYPERLIQUID_DEX,
  });

  const idx = meta.universe.findIndex((asset) => asset.name === HYPERLIQUID_COIN);

  if (idx < 0) {
    throw new Error("Could not find Hyperliquid market xyz:SKHX.");
  }

  const ctx = ctxs[idx];
  return Number(ctx.markPx ?? ctx.midPx ?? ctx.oraclePx);
}

async function yahooPrice(symbol) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1m&range=1d`;
  const res = await fetch(url);

  if (!res.ok) throw new Error(`Yahoo fetch failed for ${symbol}: ${res.status}`);

  const json = await res.json();
  const result = json.chart.result?.[0];
  const meta = result?.meta;
  const price = meta?.regularMarketPrice ?? meta?.previousClose;

  if (!price) throw new Error(`Could not fetch price for ${symbol}.`);
  return Number(price);
}

try {
  const [hynixPrice, fx, wtiOil, us10yRaw] = await Promise.all([
    getHynixPrice(),
    yahooPrice(FX_SYMBOL),
    yahooPrice(WTI_SYMBOL),
    yahooPrice(US10Y_SYMBOL),
  ]);

  // Yahoo ^TNX is commonly quoted as 10x the yield. Example: 42.50 means 4.25%.
  const us10yYield = us10yRaw > 20 ? us10yRaw / 10 : us10yRaw;


  const message =
`<b>가격 알람</b>
<pre>${escapeHtml(
`Hynix Price   ${fmtUsd(hynixPrice)}
환율          ${fmtFx(fx)}
WTI OIL       ${fmtUsd(wtiOil)}
미국채 10Y    ${fmtPct(us10yYield)}`
)}</pre>`;

  await sendTelegram(message);
  console.log("Alert sent.");
} catch (err) {
  const message =
`<b>가격 알람 오류</b>

<pre>${escapeHtml(err.message)}</pre>`;

  await sendTelegram(message);
  throw err;
}
