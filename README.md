# Crypto Telegram Alerts

Merkl의 새 Opportunities와 주요 거래소의 Earn/Launchpool/Launchpad류 이벤트를 Telegram으로 알려주는 GitHub Actions 모니터입니다.

## 동작 방식

- `Merkl Telegram Alerts`: GitHub Actions가 약 15분마다 Merkl API를 확인합니다.
- `Exchange Earn Event Alerts`: Binance, Bybit, Bitget의 공지/이벤트 페이지를 약 15분마다 확인합니다.
- 처음 실행할 때는 현재 목록을 상태 파일에 저장만 합니다.
- 이후 실행부터 새로 발견된 항목만 Telegram으로 보냅니다.
- PC를 켜둘 필요가 없습니다.

## 필요한 GitHub Secrets

Repository Settings -> Secrets and variables -> Actions -> New repository secret에서 아래 값을 추가하세요.

- `TELEGRAM_BOT_TOKEN`: BotFather에서 받은 Telegram 봇 토큰
- `TELEGRAM_CHAT_ID`: 알림을 받을 채팅 ID

토큰은 코드나 README에 직접 적지 마세요.

## Telegram chat_id 얻기

1. Telegram에서 `@BotFather`로 봇을 만듭니다.
2. 새 봇에게 아무 메시지나 보냅니다.
3. 브라우저에서 아래 주소를 엽니다.

```text
https://api.telegram.org/botYOUR_TOKEN/getUpdates
```

응답 안의 `chat.id` 값을 `TELEGRAM_CHAT_ID`로 저장하면 됩니다.

그룹이나 채널로 보내려면 봇을 먼저 초대하세요. 채널에서는 봇을 admin으로 올려야 합니다.

## 수동 실행

Actions 탭에서 원하는 workflow를 선택한 뒤 `Run workflow`를 누르면 즉시 실행할 수 있습니다.

- `send_initial=false`: 현재 목록을 기준점으로만 저장합니다.
- `send_initial=true`: 현재 목록도 Telegram으로 보냅니다.

## 설정

Merkl 기본값은 `.github/workflows/merkl.yml`에 있습니다.

- 실행 주기: 매시간 7, 22, 37, 52분
- API URL: `https://api.merkl.xyz/v4/opportunities`
- 상태 필터: `LIVE`

거래소 이벤트 기본값은 `.github/workflows/exchanges.yml`과 `exchange_monitor.py`에 있습니다.

- 실행 주기: 매시간 11, 26, 41, 56분
- 대상: Binance, Bybit, Bitget
- 키워드: Earn, Launchpool, Launchpad, LaunchX, PoolX, Startup, HODLer, Airdrop, Staking, Subscribe, Deposit to Earn 등
- 상태 파일: `exchange_seen_events.json`

## 참고

이 repo가 public이어도 GitHub Secrets 값은 공개되지 않습니다. 다만 알림 상태 파일 `merkl_seen_opportunities.json`과 `exchange_seen_events.json`은 repo에 커밋됩니다.
