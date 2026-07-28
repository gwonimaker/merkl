const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

const HYPERLIQUID_DEX = "xyz";
const HYPERLIQUID_COIN = "xyz:SKHX";
const FX_SYMBOL = process.env.FX_SYMBOL || "KRW=X";
const WTI_SYMBOL = process.env.WTI_SYMBOL || "CL=F";
const US10Y_SYMBOL = process.env.US10Y_SYMBOL || "^TNX";
const TARGET_MINUTES = (process.env.TARGET_MINUTES || "13,33,53")
  .split(",")
  .map((value) => Number(value.trim()))
  .filter((value) => Number.isInteger(value) && value >= 0 && value <= 59);
const MAX_WAIT_MS = Number(process.env.MAX_WAIT_MINUTES || "7") * 60 * 1000;
const SEND_GRACE_MS = Number(process.env.SEND_GRACE_MINUTES || "2") * 60 * 1000;

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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function targetDelaysMs(now = new Date()) {
  const nextDelays = [];
  const previousDelays = [];

  for (const minute of TARGET_MINUTES) {
    const next = new Date(now);
    next.setUTCSeconds(0, 0);
    next.setUTCMinutes(minute);

    while (next.getTime() < now.getTime()) {
      next.setUTCHours(next.getUTCHours() + 1);
    }

    const previous = new Date(now);
    previous.setUTCSeconds(0, 0);
    previous.setUTCMinutes(minute);

    while (previous.getTime() > now.getTime()) {
      previous.setUTCHours(previous.getUTCHours() - 1);
    }

    nextDelays.push(next.getTime() - now.getTime());
    previousDelays.push(now.getTime() - previous.getTime());
  }

  return {
    next: Math.min(...nextDelays),
    previous: Math.min(...previousDelays),
  };
}

async function waitForTargetMinute() {
  if (process.env.GITHUB_EVENT_NAME !== "schedule") return true;
  if (TARGET_MINUTES.length === 0) return true;

  const { next, previous } = targetDelaysMs();

  if (previous <= SEND_GRACE_MS) {
    console.log("Already inside the target minute grace window.");
    return true;
  }

  if (next > 0 && next <= MAX_WAIT_MS) {
    console.log(`Waiting ${Math.round(next / 1000)}s for the target minute.`);
    await sleep(next);
    return true;
  }

  console.log(`Skipping stale schedule run. Next target is ${Math.round(next / 1000)}s away.`);
  return false;
}

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
  const shouldSend = await waitForTargetMinute();

  if (!shouldSend) {
    process.exit(0);
  }

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
