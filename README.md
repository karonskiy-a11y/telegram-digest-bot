# 📡 Telegram Digest Bot

AI-powered Telegram channel monitoring with two-stage analysis pipeline.

Parses 200+ channels → filters noise with fast AI → generates structured digest with powerful AI → delivers to your Telegram bot.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────┐
│  Telethon    │────▶│ Claude Haiku │────▶│ Claude Opus  │────▶│ Telegram │
│  (parsing)   │     │  (filter)    │     │  (analysis)  │     │   Bot    │
│  200+ channels     │  scores 1-10 │     │  structured  │     │  digest  │
│  3s delay    │     │  drops noise │     │  digest      │     │  to you  │
└─────────────┘     └──────────────┘     └──────────────┘     └──────────┘
      ↓                    ↓                    ↓
   ~1000 posts         ~200 posts          1 digest
   per cycle           after filter        with actions
```

## Why Two Models?

**Claude 3.5 Haiku** (fast, cheap) — scans hundreds of posts, scores each for relevance. Drops 70-80% of noise. Costs pennies.

**Claude Opus 4** (powerful, expensive) — receives only filtered posts, generates structured analysis with specific recommendations. Worth every cent, but only on quality input.

Don't run expensive models on garbage. Filter first, think second. 5x cost savings.

## What the Digest Includes

- 🔥 **Signals** — top events with context
- 💥 **Hot posts** — anomalous engagement (reactions, comments, forwards)
- 💬 **Discussion** — what people are talking about
- 🎯 **Comment opportunities** — posts worth reacting to, with suggested angles
- 📝 **Content ideas** — topics for your channel with key points
- 📱 **Platform updates** — ad platform changes
- 💾 **Knowledge base** — materials to save by category

## Features

- Engagement tracking (views, reactions, replies, forwards)
- Ad filtering (skips posts with erid markers)
- FloodWait handling (respects Telegram rate limits)
- Multi-user support
- Channel management via bot commands
- Scheduled delivery (cron)
- Auto-restart via systemd

## Setup

### 1. Get your keys

| Key | Where |
|-----|-------|
| `TG_API_ID` + `TG_API_HASH` | [my.telegram.org](https://my.telegram.org) |
| `TG_BOT_TOKEN` | [@BotFather](https://t.me/BotFather) |
| `ADMIN_CHAT_ID` | [@userinfobot](https://t.me/userinfobot) |
| `OPENROUTER_KEY` | [openrouter.ai](https://openrouter.ai) |

### 2. Install

```bash
mkdir ~/tg_digest_bot && cd ~/tg_digest_bot
python3 -m venv venv && source venv/bin/activate
pip install telethon requests python-dotenv apscheduler
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your keys
```

### 4. Add channels

Edit `channels.json` — group channels by topic:

```json
{
  "pharma": ["@channel1", "@channel2"],
  "marketing": ["@channel3", "@channel4"],
  "tech": ["@channel5"]
}
```

### 5. First run

```bash
python -u bot.py
```

First launch will ask for your phone number and Telegram auth code. This is one-time — session is saved.

### 6. Auto-start (systemd)

```bash
sudo cat > /etc/systemd/system/tg-digest.service << 'EOF'
[Unit]
Description=Telegram Digest Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/tg_digest_bot
ExecStart=/root/tg_digest_bot/venv/bin/python -u bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable tg-digest
sudo systemctl start tg-digest
```

## Bot Commands

| Command | Action |
|---------|--------|
| `/digest` | Run digest now |
| `/channels` | List all channels |
| `/add @channel group` | Add channel to group |
| `/remove @channel` | Remove channel |
| `/help` | Show help |

## Rate Limits & FloodWait

Telegram will ban your account temporarily if you parse too fast.

| Channels | Delay | Time | Risk |
|----------|-------|------|------|
| 50 | 1.5s | 1 min | ⚠️ Borderline |
| 100 | 3s | 5 min | ✅ Safe |
| 200 | 3s | 10 min | ✅ Safe |
| 200 | 1.5s | 5 min | 🔴 Ban likely |

**Rule of thumb:** keep under 20 requests/minute. 3 seconds between channels is the safe minimum.

## Cost

With 200 channels, 2 digests/day via OpenRouter:

- Haiku (filtering): ~$0.50/day
- Opus (digest): ~$2.00/day
- **Total: ~$2.50/day ≈ $75/month**

## Customization

The real value is in two places:

1. **Channel curation** — your list of 200+ channels built over years of industry experience
2. **Prompts** — filter and digest prompts tuned for your specific niche

The prompts in this repo are generic templates. Customize them for your industry — this is where domain expertise matters most.

## License

MIT
