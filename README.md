# gaggia-bot

A Discord bot that monitors a [GaggiaMate](https://github.com/jniebuhr/gaggimate)-equipped espresso machine, automatically logs every shot, posts graphs to Discord, collects tasting notes, and uses Claude AI to recommend profile adjustments.

## Features

- **Real-time shot detection** via WebSocket — no polling, instant notification when a shot ends
- **Shot graph** — 3-panel pressure / flow / temperature chart posted as a Discord embed
- **Feedback modal** — "Rate This Shot" button opens a form to log flavor score, bean, dose, yield, grind
- **Trend analysis** — Pearson correlation of scores vs. brew ratio, grind size, dose across recent shots
- **AI recommendations** — Claude Haiku synthesizes trends and heuristics into plain-English advice
- **Profile patcher** — apply recommended adjustments directly to the machine from Discord, with a confirmation step
- **Slash commands** — `/status`, `/history`, `/profile`, `/set_channel`

## Requirements

- Python 3.11+
- A [GaggiaMate](https://github.com/jniebuhr/gaggimate) display unit on your local network
- A Discord bot token and server
- An Anthropic API key

## Setup

**1. Clone and create a virtualenv**

```bash
git clone https://github.com/mestump/gaggia-bot
cd gaggia-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**2. Configure environment**

```bash
cp .env.example .env
```

Edit `.env`:

```
DISCORD_BOT_TOKEN=your_bot_token
DISCORD_GUILD_ID=your_server_id
DISCORD_ALERT_CHANNEL_ID=your_channel_id   # optional; or use /set_channel
GAGGIA_IP=192.168.x.x                      # your GaggiaMate's local IP
ANTHROPIC_API_KEY=your_anthropic_key
```

**3. Verify connectivity**

```bash
python main.py --check
```

Expected:
```
[OK] DB initialized at ./data/gaggia.db
[OK] Device reachable: HTTP 200
[OK] Config loaded — all checks complete
```

**4. Run**

```bash
python main.py
```

## Discord Bot Setup

1. Create a bot at [discord.com/developers](https://discord.com/developers/applications)
2. Enable **Message Content Intent** under Bot → Privileged Gateway Intents
3. Invite to your server with scopes: `bot`, `applications.commands`; permissions: `Send Messages`, `Embed Links`, `Attach Files`
4. Use `/set_channel #channel` in Discord to designate where shot alerts appear

## Systemd Service (optional)

Edit `gaggia-bot.service` — replace the `REPLACE_WITH_*` placeholders with your username and install path — then:

```bash
bash install.sh
```

## How It Works

```
GaggiaMate WebSocket
       │
       ▼
  ShotPoller (monitor/poller.py)
  ├── detects shot end via process.e flag
  ├── fetches shot metadata via WS req:history:list
  └── fetches binary SLOG file (/api/history/XXXXXX.slog) for telemetry
       │
       ▼
  Alerts cog (bot/cogs/alerts.py)
  ├── generates shot graph (grapher/shot_graph.py)
  ├── posts embed + PNG to Discord
  └── presents "Rate This Shot" button
       │
       ▼ (after feedback submitted)
  Recommendations cog (bot/cogs/recommendations.py)
  ├── compute_trends() — Pearson r across recent shots
  ├── diagnose_shot() — keyword-based extraction heuristic
  ├── generate_recommendation() — Claude Haiku synthesis
  └── posts recommendation embed with optional "Apply Profile" button
       │
       ▼ (if user confirms)
  profile_patcher.py
  ├── snapshots current profile to DB
  ├── applies adjustments via PUT /api/profile
  └── verifies write succeeded
```

### GaggiaMate API

The bot communicates with GaggiaMate via:

| Endpoint | Format | Used for |
|----------|--------|----------|
| `ws://<device>/ws` | JSON events | Real-time status, shot detection, `req:history:list` metadata |
| `GET /api/history/XXXXXX.slog` | Binary (SLOG) | Per-shot telemetry at 250ms resolution |
| `GET /api/status` | JSON | Current temp, mode |
| `PUT /api/profile` | JSON | Apply profile changes |

Shot detection uses the `process.e` flag in `evt:status` WebSocket events, with a fallback to mode transition (`m: 1 → 0`).

## Project Structure

```
gaggia-bot/
├── main.py                  # entrypoint — wires poller + Discord bot
├── config.py                # env var loading
├── db.py                    # SQLite schema + async context manager
├── profile_patcher.py       # safe profile snapshot + patch
├── monitor/
│   ├── fetcher.py           # GaggiaMateClient — SLOG binary parser + HTTP client
│   └── poller.py            # WebSocket listener, shot detection, WS request mux
├── grapher/
│   └── shot_graph.py        # matplotlib 3-panel shot graph
├── bot/
│   ├── client.py            # discord.py Bot setup
│   ├── embeds.py            # embed builders
│   └── cogs/
│       ├── commands.py      # slash commands
│       ├── alerts.py        # shot alert + feedback modal
│       └── recommendations.py  # recommendation flow
├── analysis/
│   ├── heuristics.py        # extraction diagnosis by tasting note keywords
│   ├── trends.py            # Pearson correlation trend analysis
│   ├── shot_transformer.py  # telemetry → AI-friendly summary + compliance metrics
│   └── llm.py               # Claude Haiku recommendation synthesis
├── tests/                   # 50 unit tests
├── docs/
│   ├── api_schema.json      # documented GaggiaMate API schemas
│   └── websocket_events.md  # observed WebSocket event samples
├── gaggia-bot.service       # systemd unit
└── install.sh               # systemd install helper
```

## Tests

```bash
pytest tests/ -v
```

70 tests covering binary parsers, shot detection, WS multiplexing, shot transformer, graph generation, embed builders, heuristics, trend analysis, recommendation flow, and profile patcher.

## Database Schema

SQLite at `./data/gaggia.db`:

| Table | Purpose |
|-------|---------|
| `shots` | Shot records with telemetry path |
| `feedback` | Tasting notes, scores, dose/yield |
| `profiles` | Profile snapshots before each patch |
| `recommendations` | AI-generated recommendations |
| `config` | Key-value store (e.g. alert channel ID) |

`feedback.brew_ratio` is a virtual generated column (`yield_g / dose_g`).

## Acknowledgements

- [GaggiaMate](https://github.com/jniebuhr/gaggimate) - The incredible project that inspired and enabled this entire thing
- [charleshall888](https://github.com/charleshall888) — shot telemetry transformation concepts in [gaggimate-barista](https://github.com/charleshall888/gaggimate-barista) inspired the approach in `analysis/shot_transformer.py`

## License

Licensed under CC BY-NC-SA 4.0  
https://creativecommons.org/licenses/by-nc-sa/4.0/
