"""
Telegram Digest Bot — AI-powered channel monitoring and analysis.

Parses Telegram channels, filters posts through AI, delivers structured digest.
Two-stage AI pipeline: fast model filters noise, powerful model generates analysis.

Stack: Python + Telethon + OpenRouter (Claude) + systemd
Author: @your_channel
"""

import os, json, asyncio, logging, requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv
from telethon import TelegramClient, events
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ─── Config ───────────────────────────────────────────
load_dotenv()

API_ID = int(os.getenv("TG_API_ID", 0))
API_HASH = os.getenv("TG_API_HASH", "")
BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", 0))
ALLOWED_USERS = json.loads(os.getenv("ALLOWED_USERS", f"[{ADMIN_CHAT_ID}]"))
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")

SCHEDULE_HOURS = json.loads(os.getenv("SCHEDULE_HOURS", "[7, 19]"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", 12))
MAX_POSTS_PER_CHANNEL = int(os.getenv("MAX_POSTS_PER_CHANNEL", 50))
MIN_VIEWS = int(os.getenv("MIN_VIEWS", 0))
CHANNEL_TOPIC = os.getenv("CHANNEL_TOPIC", "your niche here")

# Models — cheap for filtering, powerful for analysis
FILTER_MODEL = os.getenv("FILTER_MODEL", "anthropic/claude-3.5-haiku")
DIGEST_MODEL = os.getenv("DIGEST_MODEL", "anthropic/claude-opus-4")

CHANNELS_FILE = Path(__file__).parent / "channels.json"

# ─── Logging ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("digest")

# ─── Clients ──────────────────────────────────────────
userbot = TelegramClient("userbot_session", API_ID, API_HASH)
bot = TelegramClient("bot_session", API_ID, API_HASH)


# ─── LLM ──────────────────────────────────────────────
def llm_call(model, prompt, max_tokens=4096):
    """Call LLM through OpenRouter API."""
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + OPENROUTER_KEY,
            "Content-Type": "application/json"
        },
        json={
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    return r.json()["choices"][0]["message"]["content"]


# ─── Channels ─────────────────────────────────────────
def load_channels():
    if CHANNELS_FILE.exists():
        return json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
    default = {"general": []}
    CHANNELS_FILE.write_text(json.dumps(default, indent=2, ensure_ascii=False))
    return default


def save_channels(data):
    CHANNELS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


# ─── Parsing ──────────────────────────────────────────
async def fetch_channel_posts(channel, since):
    """Fetch posts from a single channel with engagement metrics."""
    posts = []
    try:
        entity = await userbot.get_entity(channel)
        async for msg in userbot.iter_messages(
            entity, limit=MAX_POSTS_PER_CHANNEL,
            offset_date=datetime.now(timezone.utc)
        ):
            if msg.date.replace(tzinfo=timezone.utc) < since:
                break
            if not msg.text:
                continue
            if MIN_VIEWS and (msg.views or 0) < MIN_VIEWS:
                continue

            # Skip ads (erid = Russian ad marker)
            if "erid" in msg.text.lower():
                continue

            # Collect engagement metrics
            reactions = 0
            if hasattr(msg, "reactions") and msg.reactions:
                for r in msg.reactions.results:
                    reactions += r.count
            replies = msg.replies.replies if hasattr(msg, "replies") and msg.replies else 0
            forwards = msg.forwards or 0

            posts.append({
                "channel": channel,
                "text": msg.text[:1500],
                "date": msg.date.isoformat(),
                "views": msg.views or 0,
                "reactions": reactions,
                "replies": replies,
                "forwards": forwards,
                "link": f"https://t.me/{channel.lstrip('@')}/{msg.id}"
            })
    except Exception as e:
        if "wait" in str(e).lower():
            log.warning(f"FloodWait for {channel}, skipping")
        else:
            log.warning(f"Error parsing {channel}: {e}")
    return posts


async def fetch_all_posts():
    """Fetch posts from all channel groups."""
    channels = load_channels()
    since = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    result = {}

    for group, ch_list in channels.items():
        group_posts = []
        for ch in ch_list:
            log.info(f"Parsing {ch}")
            posts = await fetch_channel_posts(ch, since)
            group_posts.extend(posts)
            await asyncio.sleep(3)  # Respect Telegram rate limits!

        group_posts.sort(key=lambda p: p["views"], reverse=True)
        result[group] = group_posts
        log.info(f"Group '{group}': {len(group_posts)} posts")

    return result


def format_posts(posts):
    """Format posts for LLM prompt with engagement data."""
    lines = []
    for p in posts:
        engagement = (
            f"[{p['channel']}] views:{p['views']} "
            f"reactions:{p.get('reactions', 0)} "
            f"replies:{p.get('replies', 0)} "
            f"fwd:{p.get('forwards', 0)}"
        )
        lines.append(f"{engagement} {p['link']}\n{p['text']}\n---")
    return "\n".join(lines)


# ─── AI Pipeline ──────────────────────────────────────
async def filter_posts(group, posts):
    """Stage 1: Fast model filters noise, scores relevance."""
    if not posts:
        return []

    filtered = []
    for i in range(0, len(posts), 50):
        batch = posts[i:i + 50]

        # ──────────────────────────────────────────────
        # CUSTOMIZE THIS PROMPT FOR YOUR NICHE
        # This is where domain expertise matters most
        # ──────────────────────────────────────────────
        prompt = (
            f"ROLE: Expert analyst for a Telegram channel about {CHANNEL_TOPIC}.\n"
            f"Posts from group '{group}':\n\n"
            f"{format_posts(batch)}\n"
            f"Score 1-10 for relevance. Posts with HIGH reactions/replies are extra important.\n"
            f"Labels: COMMENT, DEEP_DIVE, SAVE_TO_KB, WATCHLIST, SKIP.\n"
            f"Return JSON, ONLY score>=3:\n"
            f'[{{"link":"...","channel":"...","score":N,"summary":"Russian","labels":["COMMENT"],"why":"why important, Russian"}}]\n'
            f"JSON only."
        )

        try:
            text = llm_call(FILTER_MODEL, prompt).strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            items = json.loads(text)
            filtered.extend(items)
        except Exception as e:
            log.warning(f"Filter error: {e}")
            # Fallback: take top posts by views
            top_n = max(len(batch) // 2, 7)
            for p in batch[:top_n]:
                filtered.append({
                    "link": p["link"],
                    "channel": p["channel"],
                    "score": 7,
                    "summary": p["text"][:200],
                    "labels": ["COMMENT"],
                    "why": ""
                })

    log.info(f"Group '{group}': {len(posts)} -> {len(filtered)} after filter")
    return filtered


async def generate_digest(all_filtered):
    """Stage 2: Powerful model generates structured digest."""
    combined = []
    for group, posts in all_filtered.items():
        for p in posts:
            combined.append(
                f"[{p['channel']}] score:{p['score']} {p['link']}\n"
                f"{p.get('why', '')} {p['summary']}"
            )

    if not combined:
        return "No interesting posts found."

    # Current date for the digest header
    now = datetime.now(timezone(timedelta(hours=3)))  # Moscow time
    weekdays = [
        "понедельник", "вторник", "среда", "четверг",
        "пятница", "суббота", "воскресенье"
    ]
    today = f"{now.strftime('%d.%m.%Y')}, {weekdays[now.weekday()]}"

    # ──────────────────────────────────────────────────
    # CUSTOMIZE THIS PROMPT FOR YOUR NICHE
    # This is the core of your product's value
    # ──────────────────────────────────────────────────
    prompt = f"""You are an expert analyst for a Telegram channel about {CHANNEL_TOPIC}. Today is {today}.

Here are filtered posts with engagement metrics:

{"---".join(combined)}

Create a DETAILED digest in Russian. Telegram Markdown format.
Include sections: trends, hot posts (high engagement), discussion topics,
posts to comment on, content ideas, platform updates, knowledge base materials.

RULES:
- Use ONLY facts and links from posts above
- NEVER invent facts or links
- Write in Russian, business tone
- Maximum links and specifics
- All section headers in Russian with emoji"""

    try:
        return llm_call(DIGEST_MODEL, prompt)
    except Exception as e:
        log.error(f"Digest error: {e}")
        return f"Digest error: {e}"


# ─── Delivery ─────────────────────────────────────────
async def send_digest(text, chat_id=None):
    """Send digest to Telegram, splitting long messages."""
    targets = [chat_id] if chat_id else ALLOWED_USERS
    for uid in targets:
        parts = []
        t = text
        while t:
            if len(t) <= 4000:
                parts.append(t)
                break
            cut = t[:4000].rfind("\n\n")
            if cut == -1:
                cut = t[:4000].rfind("\n")
            if cut == -1:
                cut = 4000
            parts.append(t[:cut])
            t = t[cut:].lstrip()

        for part in parts:
            try:
                await bot.send_message(uid, part, parse_mode="md", link_preview=False)
            except Exception:
                await bot.send_message(uid, part, link_preview=False)
            await asyncio.sleep(0.5)


async def run_digest(chat_id=None):
    """Full pipeline: parse → filter → digest → deliver."""
    log.info("=== Starting digest ===")
    all_posts = await fetch_all_posts()
    total = sum(len(p) for p in all_posts.values())
    log.info(f"Total: {total} posts")

    if total == 0:
        await send_digest("No new posts found.", chat_id)
        return

    all_filtered = {}
    for group, posts in all_posts.items():
        all_filtered[group] = await filter_posts(group, posts)

    digest = await generate_digest(all_filtered)
    await send_digest(digest, chat_id)
    log.info("=== Digest sent ===")


# ─── Bot Commands ─────────────────────────────────────
async def setup_bot_commands():
    @bot.on(events.NewMessage(pattern="/digest", from_users=ALLOWED_USERS))
    async def cmd_digest(event):
        await event.reply("Collecting digest...")
        await run_digest(event.chat_id)

    @bot.on(events.NewMessage(pattern="/channels", from_users=ALLOWED_USERS))
    async def cmd_channels(event):
        channels = load_channels()
        lines = []
        for group, ch_list in channels.items():
            lines.append(f"**{group}** ({len(ch_list)}):")
            for ch in ch_list:
                lines.append(f"  {ch}")
        text = "\n".join(lines) if lines else "Channel list is empty."
        await event.reply(text, parse_mode="md")

    @bot.on(events.NewMessage(pattern=r"/add (\S+)\s*(.*)", from_users=ALLOWED_USERS))
    async def cmd_add(event):
        channel = event.pattern_match.group(1)
        group = event.pattern_match.group(2).strip() or "general"
        channels = load_channels()
        if group not in channels:
            channels[group] = []
        if channel not in channels[group]:
            channels[group].append(channel)
            save_channels(channels)
            await event.reply(f"Added {channel} to '{group}'")
        else:
            await event.reply(f"{channel} already in '{group}'")

    @bot.on(events.NewMessage(pattern=r"/remove (\S+)", from_users=ALLOWED_USERS))
    async def cmd_remove(event):
        channel = event.pattern_match.group(1)
        channels = load_channels()
        removed = False
        for group in channels:
            if channel in channels[group]:
                channels[group].remove(channel)
                removed = True
        if removed:
            save_channels(channels)
            await event.reply(f"Removed {channel}")
        else:
            await event.reply(f"{channel} not found")

    @bot.on(events.NewMessage(pattern="/help", from_users=ALLOWED_USERS))
    async def cmd_help(event):
        await event.reply(
            "/digest — run digest now\n"
            "/channels — list all channels\n"
            "/add @channel group — add channel\n"
            "/remove @channel — remove channel\n"
            "/help — this message"
        )


# ─── Main ─────────────────────────────────────────────
async def main():
    await userbot.start()
    log.info("Userbot started")

    await bot.start(bot_token=BOT_TOKEN)
    log.info("Bot started")

    await setup_bot_commands()

    scheduler = AsyncIOScheduler()
    for h in SCHEDULE_HOURS:
        scheduler.add_job(run_digest, "cron", hour=h, minute=0)
        log.info(f"Scheduled at {h}:00 UTC")
    scheduler.start()

    log.info("Ready. Waiting for commands...")
    await bot.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
