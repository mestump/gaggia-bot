# GaggiaMate Shot Intelligence Bot — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an always-on Python daemon that monitors a GaggiaMate espresso controller via WebSocket, detects shots, generates graphs, posts to Discord, collects feedback, and uses Claude AI to recommend espresso improvements.

**Architecture:** WebSocket listener (`/ws`) replaces REST polling for real-time shot detection via mode transitions (idle→brewing→idle). REST API handles history fetch, profile read/write. Discord bot (discord.py) runs concurrently via asyncio. All data persists in SQLite.

**Tech Stack:** Python 3.11+, aiohttp (WebSocket + REST), discord.py 2.3+, matplotlib, numpy, scipy, anthropic SDK, aiosqlite, python-dotenv

---

## CRITICAL API DISCOVERY

The GaggiaMate device exposes a **WebSocket at `/ws`** (not just REST).
- `StatusEvent` fires continuously with: `{tp: "StatusEvent", mode, currentTemp, targetTemp, currentPressure, targetPressure, currentFlow, targetFlow, ...}`
- Mode transitions: `idle` → `brewing` → `idle` = shot detected
- REST endpoints still used for: shot history (`/api/history`), profile CRUD

**Before implementing any monitor code**, Task 1.1 must verify live device schemas.

---

## Task 1: Project Scaffold

**Files:**
- Create: `gaggia-bot/config.py`
- Create: `gaggia-bot/db.py`
- Create: `gaggia-bot/requirements.txt`
- Create: `gaggia-bot/.env.example`
- Create: `gaggia-bot/main.py`
- Create: `gaggia-bot/monitor/__init__.py`
- Create: `gaggia-bot/grapher/__init__.py`
- Create: `gaggia-bot/bot/__init__.py`
- Create: `gaggia-bot/bot/cogs/__init__.py`
- Create: `gaggia-bot/analysis/__init__.py`
- Create: `gaggia-bot/data/.gitkeep`
- Create: `gaggia-bot/data/graphs/.gitkeep`
- Create: `gaggia-bot/.gitignore`

**Step 1: Write requirements.txt**

```
discord.py>=2.3.0
aiohttp>=3.9.0
matplotlib>=3.8.0
numpy>=1.26.0
scipy>=1.12.0
anthropic>=0.30.0
python-dotenv>=1.0.0
aiosqlite>=0.20.0
```

**Step 2: Write .env.example**

```
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_ALERT_CHANNEL_ID=
GAGGIA_IP=<device-ip>
GAGGIA_POLL_INTERVAL=15
ANTHROPIC_API_KEY=
DB_PATH=./data/gaggia.db
GRAPH_DIR=./data/graphs
MIN_SHOTS_FOR_RECOMMENDATION=3
```

**Step 3: Write config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required env var missing: {key}")
    return val

DISCORD_BOT_TOKEN = _require("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = int(_require("DISCORD_GUILD_ID"))
DISCORD_ALERT_CHANNEL_ID = int(os.getenv("DISCORD_ALERT_CHANNEL_ID", "0"))
GAGGIA_IP = os.getenv("GAGGIA_IP", "<device-ip>")
GAGGIA_POLL_INTERVAL = int(os.getenv("GAGGIA_POLL_INTERVAL", "15"))
ANTHROPIC_API_KEY = _require("ANTHROPIC_API_KEY")
DB_PATH = os.getenv("DB_PATH", "./data/gaggia.db")
GRAPH_DIR = os.getenv("GRAPH_DIR", "./data/graphs")
MIN_SHOTS_FOR_RECOMMENDATION = int(os.getenv("MIN_SHOTS_FOR_RECOMMENDATION", "3"))
```

**Step 4: Write db.py**

```python
import aiosqlite
import asyncio
from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS shots (
  id           TEXT PRIMARY KEY,
  timestamp    DATETIME NOT NULL,
  duration_s   REAL,
  profile_name TEXT,
  raw_json     TEXT,
  graph_path   TEXT,
  posted_at    DATETIME
);

CREATE TABLE IF NOT EXISTS feedback (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id      TEXT REFERENCES shots(id),
  flavor_score INTEGER CHECK(flavor_score BETWEEN 1 AND 10),
  flavor_notes TEXT,
  bean_name    TEXT,
  roaster      TEXT,
  roast_date   DATE,
  grind_size   REAL,
  dose_g       REAL,
  yield_g      REAL,
  brew_ratio   REAL GENERATED ALWAYS AS (yield_g / dose_g) VIRTUAL,
  collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT,
  raw_json     TEXT,
  applied_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  source       TEXT CHECK(source IN ('device','bot_recommendation'))
);

CREATE TABLE IF NOT EXISTS recommendations (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  shot_id          TEXT REFERENCES shots(id),
  generated_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
  recommendation   TEXT,
  adjustments_json TEXT,
  applied          BOOLEAN DEFAULT 0,
  applied_at       DATETIME
);

CREATE TABLE IF NOT EXISTS config (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""

async def init_db():
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()

async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db
```

**Step 5: Create all __init__.py files and directory structure**

```bash
mkdir -p gaggia-bot/{monitor,grapher,bot/cogs,analysis,data/graphs,docs/plans}
touch gaggia-bot/{monitor,grapher,bot,bot/cogs,analysis}/__init__.py
touch gaggia-bot/data/.gitkeep gaggia-bot/data/graphs/.gitkeep
```

**Step 6: Write .gitignore**

```
.env
data/gaggia.db
data/graphs/*.png
__pycache__/
*.pyc
*.pyo
.venv/
venv/
```

**Step 7: Write stub main.py**

```python
import asyncio
import argparse
import sys
import config
import db

async def check_mode():
    """Validate config, DB, device ping."""
    import aiohttp
    await db.init_db()
    print(f"[OK] DB initialized at {config.DB_PATH}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{config.GAGGIA_IP}/api/status", timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                print(f"[OK] Device reachable: HTTP {resp.status}")
    except Exception as e:
        print(f"[WARN] Device not reachable: {e}")
    print("[OK] Config loaded")
    print("[OK] Check complete")

async def main():
    await db.init_db()
    # Will be wired up in Task 7
    print("GaggiaMate bot starting... (stub)")
    await asyncio.sleep(999999)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        asyncio.run(check_mode())
    else:
        asyncio.run(main())
```

**Step 8: Install deps and verify**

```bash
cd ~/gaggia-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --check
```

Expected: `[OK] Config loaded` (device may be unreachable if not on local network — that's fine)

**Step 9: Commit**

```bash
git init
git add requirements.txt .env.example config.py db.py main.py .gitignore \
        monitor/__init__.py grapher/__init__.py bot/__init__.py \
        bot/cogs/__init__.py analysis/__init__.py
git commit -m "feat: project scaffold — config, db schema, directory structure"
```

---

## Task 2: API Audit (run on machine with network access to <device-ip>)

**Files:**
- Create: `docs/api_schema.json`
- Create: `docs/websocket_events.md`

**Step 1: Enumerate REST endpoints**

```bash
curl -s http://<device-ip>/api/ | python3 -m json.tool
curl -s http://<device-ip>/api/status | python3 -m json.tool
curl -s http://<device-ip>/api/history | python3 -m json.tool
curl -s http://<device-ip>/api/profile | python3 -m json.tool
curl -s http://<device-ip>/api/profiles | python3 -m json.tool
```

**Step 2: Capture one full shot history entry**

```bash
# Get first shot ID from history list
SHOT_ID=$(curl -s http://<device-ip>/api/history | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['id'] if isinstance(d,list) else list(d.values())[0][0]['id'])")
curl -s "http://<device-ip>/api/history/$SHOT_ID" | python3 -m json.tool > docs/api_schema.json
```

**Step 3: Test WebSocket connection**

```python
# Save as docs/ws_test.py and run it
import asyncio, aiohttp, json

async def test_ws():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("ws://<device-ip>/ws") as ws:
            print("Connected. Listening for 10 seconds...")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    print(f"tp={data.get('tp')}: {json.dumps(data, indent=2)}")
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break

asyncio.run(test_ws())
```

Run: `python3 docs/ws_test.py`

Expected: Stream of `StatusEvent` messages with real-time machine state.

**Step 4: Document findings**

Save full JSON schemas to `docs/api_schema.json`. Note:
- Exact field names in StatusEvent (camelCase vs snake_case)
- Whether history endpoint returns array or paginated object
- Whether shot IDs are integers, UUIDs, or timestamps
- Auth headers required (likely none)

**Step 5: Update PRD section 4 with verified schemas (in-place edit)**

**Step 6: Commit**

```bash
git add docs/
git commit -m "docs: verified GaggiaMate API schemas and WebSocket event structure"
```

---

## Task 3: Shot Monitor — WebSocket Listener + REST Fetcher

**Files:**
- Create: `monitor/fetcher.py`
- Create: `monitor/poller.py`
- Create: `tests/test_fetcher.py`

**Step 1: Write failing test for fetcher**

```python
# tests/test_fetcher.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from monitor.fetcher import GaggiaMateClient

@pytest.mark.asyncio
async def test_get_status_returns_dict():
    client = GaggiaMateClient("<device-ip>")
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value={"mode": "idle"})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        async with aiohttp.ClientSession() as session:
            result = await client.get_status(session)
    assert result["mode"] == "idle"

@pytest.mark.asyncio
async def test_get_history_returns_list():
    client = GaggiaMateClient("<device-ip>")
    mock_resp = AsyncMock()
    mock_resp.json = AsyncMock(return_value=[{"id": "abc", "timestamp": "2026-03-07T08:00:00"}])
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=None)
    with patch("aiohttp.ClientSession.get", return_value=mock_resp):
        async with aiohttp.ClientSession() as session:
            result = await client.get_history(session)
    assert isinstance(result, list)
    assert result[0]["id"] == "abc"
```

**Step 2: Run test to confirm failure**

```bash
pytest tests/test_fetcher.py -v
```

Expected: `ImportError: cannot import name 'GaggiaMateClient'`

**Step 3: Write monitor/fetcher.py**

```python
import asyncio
import logging
from typing import Any
import aiohttp

logger = logging.getLogger(__name__)
RETRY_DELAYS = [1, 2, 5, 10, 30]

class GaggiaMateClient:
    def __init__(self, ip: str):
        self.base = f"http://{ip}"
        self.ws_url = f"ws://{ip}/ws"

    async def _get(self, session: aiohttp.ClientSession, path: str) -> Any:
        for delay in RETRY_DELAYS + [None]:
            try:
                async with session.get(
                    f"{self.base}{path}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                if delay is None:
                    logger.error("Fetcher giving up on %s: %s", path, e)
                    raise
                logger.warning("Fetch %s failed (%s), retrying in %ss", path, e, delay)
                await asyncio.sleep(delay)

    async def get_status(self, session: aiohttp.ClientSession) -> dict:
        return await self._get(session, "/api/status")

    async def get_history(self, session: aiohttp.ClientSession) -> list:
        result = await self._get(session, "/api/history")
        return result if isinstance(result, list) else result.get("shots", [])

    async def get_shot(self, session: aiohttp.ClientSession, shot_id: str) -> dict:
        return await self._get(session, f"/api/history/{shot_id}")

    async def get_profile(self, session: aiohttp.ClientSession) -> dict:
        return await self._get(session, "/api/profile")

    async def get_profiles(self, session: aiohttp.ClientSession) -> list:
        result = await self._get(session, "/api/profiles")
        return result if isinstance(result, list) else result.get("profiles", [])

    async def put_profile(self, session: aiohttp.ClientSession, profile: dict) -> dict:
        async with session.put(
            f"{self.base}/api/profile",
            json=profile,
            timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()
```

**Step 4: Run tests to confirm pass**

```bash
pytest tests/test_fetcher.py -v
```

Expected: PASS

**Step 5: Write monitor/poller.py — WebSocket-based shot detector**

```python
import asyncio
import json
import logging
from typing import Callable, Awaitable
import aiohttp
from monitor.fetcher import GaggiaMateClient
import db

logger = logging.getLogger(__name__)

BREWING_MODES = {"brewing", "espresso", "shot"}  # adjust after Task 2 audit

class ShotPoller:
    def __init__(self, client: GaggiaMateClient, on_shot: Callable[[dict], Awaitable[None]]):
        self.client = client
        self.on_shot = on_shot
        self._last_mode = None
        self._shot_start_time = None
        self._running = False

    async def run(self):
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except Exception as e:
                logger.error("WebSocket disconnected: %s. Reconnecting in 5s...", e)
                await asyncio.sleep(5)

    async def _connect_and_listen(self):
        async with aiohttp.ClientSession() as session:
            logger.info("Connecting to WebSocket at %s", self.client.ws_url)
            async with session.ws_connect(self.client.ws_url) as ws:
                logger.info("WebSocket connected")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        await self._handle_message(json.loads(msg.data), session)
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                        break

    async def _handle_message(self, data: dict, session: aiohttp.ClientSession):
        if data.get("tp") != "StatusEvent":
            return
        mode = data.get("mode", "").lower()
        was_brewing = self._last_mode in BREWING_MODES
        is_brewing = mode in BREWING_MODES

        if not was_brewing and is_brewing:
            logger.info("Shot started (mode=%s)", mode)
        elif was_brewing and not is_brewing:
            logger.info("Shot ended (mode=%s). Fetching history...", mode)
            await asyncio.sleep(2)  # brief delay for device to write history
            await self._fetch_new_shots(session)

        self._last_mode = mode

    async def _fetch_new_shots(self, session: aiohttp.ClientSession):
        try:
            history = await self.client.get_history(session)
            known_ids = await self._get_known_ids()
            for entry in history:
                shot_id = str(entry.get("id", ""))
                if shot_id and shot_id not in known_ids:
                    full = await self.client.get_shot(session, shot_id)
                    profile = await self.client.get_profile(session)
                    await self._save_shot(full, profile)
                    await self.on_shot({"shot": full, "profile": profile})
        except Exception as e:
            logger.error("Failed to fetch new shots: %s", e)

    async def _get_known_ids(self) -> set:
        async with await db.get_db() as conn:
            async with conn.execute("SELECT id FROM shots") as cur:
                rows = await cur.fetchall()
        return {row["id"] for row in rows}

    async def _save_shot(self, shot: dict, profile: dict):
        import json as _json
        from datetime import datetime
        async with await db.get_db() as conn:
            await conn.execute(
                "INSERT OR IGNORE INTO shots (id, timestamp, duration_s, profile_name, raw_json) VALUES (?,?,?,?,?)",
                (
                    str(shot.get("id")),
                    shot.get("timestamp", datetime.utcnow().isoformat()),
                    shot.get("duration_s"),
                    shot.get("profile_name") or profile.get("name"),
                    _json.dumps(shot),
                )
            )
            await conn.commit()

    def stop(self):
        self._running = False
```

**Step 6: Write failing integration test for poller shot detection**

```python
# tests/test_poller.py
import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from monitor.poller import ShotPoller
from monitor.fetcher import GaggiaMateClient

@pytest.mark.asyncio
async def test_shot_detected_on_mode_transition():
    shots_seen = []
    client = GaggiaMateClient("<device-ip>")
    poller = ShotPoller(client, on_shot=lambda s: shots_seen.append(s) or asyncio.coroutine(lambda: None)())

    # Simulate brewing→idle transition
    with patch.object(poller, "_fetch_new_shots", new=AsyncMock()) as mock_fetch:
        await poller._handle_message({"tp": "StatusEvent", "mode": "brewing"}, None)
        await poller._handle_message({"tp": "StatusEvent", "mode": "idle"}, None)
        mock_fetch.assert_awaited_once()
```

**Step 7: Run test, confirm pass**

```bash
pytest tests/test_poller.py -v
```

**Step 8: Commit**

```bash
git add monitor/ tests/
git commit -m "feat: WebSocket shot monitor — fetcher + mode-transition poller"
```

---

## Task 4: Graph Generation

**Files:**
- Create: `grapher/shot_graph.py`
- Create: `tests/test_graph.py`
- Create: `tests/fixtures/sample_shot.json`

**Step 1: Create sample fixture**

```json
{
  "id": "test-shot-001",
  "timestamp": "2026-03-07T08:22:00",
  "duration_s": 28,
  "profile_name": "Trieste v2",
  "datapoints": [
    {"t": 0.0, "pressure": 0.0, "flow": 0.0, "temperature": 93.0, "weight": 0.0},
    {"t": 2.0, "pressure": 1.5, "flow": 0.5, "temperature": 93.1, "weight": 0.5},
    {"t": 8.0, "pressure": 4.0, "flow": 1.2, "temperature": 93.2, "weight": 5.0},
    {"t": 15.0, "pressure": 9.0, "flow": 2.1, "temperature": 93.0, "weight": 15.0},
    {"t": 22.0, "pressure": 8.5, "flow": 1.9, "temperature": 92.9, "weight": 25.0},
    {"t": 28.0, "pressure": 7.0, "flow": 1.5, "temperature": 92.8, "weight": 36.0}
  ]
}
```

**Step 2: Write failing test**

```python
# tests/test_graph.py
import pytest
import json
from pathlib import Path
from grapher.shot_graph import generate_shot_graph

FIXTURE = Path("tests/fixtures/sample_shot.json")

def test_graph_generates_png(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    output = generate_shot_graph(shot, output_dir=tmp_path)
    assert output.exists()
    assert output.suffix == ".png"
    assert output.stat().st_size > 10_000  # not an empty file

def test_graph_with_feedback(tmp_path):
    shot = json.loads(FIXTURE.read_text())
    feedback = {"dose_g": 18.0, "yield_g": 36.0, "flavor_score": 8}
    output = generate_shot_graph(shot, feedback=feedback, output_dir=tmp_path)
    assert output.exists()
```

**Step 3: Run test to confirm failure**

```bash
pytest tests/test_graph.py -v
```

**Step 4: Write grapher/shot_graph.py**

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from pathlib import Path
from typing import Optional
import os

def generate_shot_graph(
    shot_data: dict,
    feedback: Optional[dict] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    if output_dir is None:
        from config import GRAPH_DIR
        output_dir = Path(GRAPH_DIR)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    shot_id = str(shot_data.get("id", "unknown"))
    datapoints = shot_data.get("datapoints", [])
    t = [d["t"] for d in datapoints]
    pressure = [d.get("pressure", 0) for d in datapoints]
    flow = [d.get("flow", 0) for d in datapoints]
    temp = [d.get("temperature", 0) for d in datapoints]
    weight = [d.get("weight", 0) for d in datapoints]

    fig = plt.figure(figsize=(12, 8))
    gs = gridspec.GridSpec(3, 1, figure=fig, hspace=0.4)
    ax1 = fig.add_subplot(gs[0])
    ax2 = fig.add_subplot(gs[1], sharex=ax1)
    ax3 = fig.add_subplot(gs[2], sharex=ax1)

    ax1.plot(t, pressure, color="steelblue", linewidth=2)
    ax1.set_ylabel("Pressure (bar)")
    ax1.set_ylim(bottom=0)
    ax1.grid(True, alpha=0.3)

    ax2.plot(t, flow, color="seagreen", linewidth=2)
    ax2.set_ylabel("Flow (ml/s)")
    ax2.set_ylim(bottom=0)
    ax2.grid(True, alpha=0.3)

    ax3.plot(t, temp, color="firebrick", linewidth=2, label="Temp (°C)")
    if any(w > 0 for w in weight):
        ax3.plot(t, weight, color="darkorange", linewidth=2, linestyle="--", label="Weight (g)")
        ax3.legend(fontsize=8)
    ax3.set_ylabel("Temp (°C) / Weight (g)")
    ax3.set_xlabel("Time (s)")
    ax3.grid(True, alpha=0.3)

    profile_name = shot_data.get("profile_name", "Unknown Profile")
    timestamp = shot_data.get("timestamp", "")[:16].replace("T", " ")
    duration = shot_data.get("duration_s", "?")
    fig.suptitle(f"{profile_name} — {timestamp} — {duration}s", fontsize=13, fontweight="bold")

    if feedback:
        dose = feedback.get("dose_g")
        yld = feedback.get("yield_g")
        score = feedback.get("flavor_score")
        ratio = f"1:{yld/dose:.1f}" if dose and yld else "?"
        footer = f"Dose: {dose or '?'}g | Yield: {yld or '?'}g | Ratio: {ratio} | Score: {score or '?'}/10"
        fig.text(0.5, 0.01, footer, ha="center", fontsize=10, color="gray")

    out_path = output_dir / f"{shot_id}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path
```

**Step 5: Run tests to confirm pass**

```bash
pytest tests/test_graph.py -v
```

**Step 6: Commit**

```bash
git add grapher/ tests/
git commit -m "feat: shot graph generator — 3-panel matplotlib PNG with feedback overlay"
```

---

## Task 5: Discord Bot Core

**Files:**
- Create: `bot/client.py`
- Create: `bot/embeds.py`
- Create: `bot/cogs/commands.py`

**Step 1: Write bot/embeds.py**

```python
import discord
from datetime import datetime

def shot_embed(shot: dict, feedback: dict | None = None) -> discord.Embed:
    profile = shot.get("profile_name", "Unknown")
    timestamp = shot.get("timestamp", "")
    duration = shot.get("duration_s", "?")
    dp = shot.get("datapoints", [])
    peak_pressure = max((d.get("pressure", 0) for d in dp), default=0)
    peak_flow = max((d.get("flow", 0) for d in dp), default=0)

    embed = discord.Embed(
        title=f"Shot: {profile}",
        color=discord.Color.dark_gold(),
        timestamp=datetime.fromisoformat(timestamp) if timestamp else datetime.utcnow(),
    )
    embed.add_field(name="Duration", value=f"{duration}s", inline=True)
    embed.add_field(name="Peak Pressure", value=f"{peak_pressure:.1f} bar", inline=True)
    embed.add_field(name="Peak Flow", value=f"{peak_flow:.2f} ml/s", inline=True)

    if feedback:
        score = feedback.get("flavor_score")
        bean = feedback.get("bean_name", "Unknown")
        ratio = None
        if feedback.get("dose_g") and feedback.get("yield_g"):
            ratio = feedback["yield_g"] / feedback["dose_g"]
        embed.add_field(name="Score", value=f"{score}/10" if score else "—", inline=True)
        embed.add_field(name="Bean", value=bean, inline=True)
        if ratio:
            embed.add_field(name="Ratio", value=f"1:{ratio:.1f}", inline=True)

    return embed

def recommendation_embed(prose: str, adjustments: list) -> discord.Embed:
    embed = discord.Embed(
        title="Shot Recommendation",
        description=prose,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    if adjustments:
        diff = "\n".join(
            f"`{a['step_name']}.{a['field']}`: {a['old_value']} → {a['new_value']}"
            for a in adjustments
        )
        embed.add_field(name="Suggested Profile Adjustments", value=diff, inline=False)
    return embed
```

**Step 2: Write bot/cogs/commands.py**

```python
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from monitor.fetcher import GaggiaMateClient
import db
import config

class Commands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.client = GaggiaMateClient(config.GAGGIA_IP)

    @app_commands.command(name="status", description="Show GaggiaMate device status")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                data = await self.client.get_status(session)
            embed = discord.Embed(title="GaggiaMate Status", color=discord.Color.green())
            for k, v in data.items():
                embed.add_field(name=k, value=str(v), inline=True)
            await interaction.followup.send(embed=embed)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="history", description="Show last N shots")
    @app_commands.describe(n="Number of shots to show (default 5)")
    async def history(self, interaction: discord.Interaction, n: int = 5):
        await interaction.response.defer()
        async with await db.get_db() as conn:
            async with conn.execute(
                "SELECT id, timestamp, duration_s, profile_name FROM shots ORDER BY timestamp DESC LIMIT ?", (n,)
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            await interaction.followup.send("No shots recorded yet.")
            return
        lines = [f"`{r['id'][:8]}` | {r['timestamp'][:16]} | {r['duration_s']}s | {r['profile_name']}" for r in rows]
        await interaction.followup.send("\n".join(lines))

    @app_commands.command(name="profile", description="Show current active profile")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            async with aiohttp.ClientSession() as session:
                data = await self.client.get_profile(session)
            import json
            text = f"```json\n{json.dumps(data, indent=2)[:1800]}\n```"
            await interaction.followup.send(text)
        except Exception as e:
            await interaction.followup.send(f"Error: {e}", ephemeral=True)

    @app_commands.command(name="set_channel", description="Set the shot alert channel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        async with await db.get_db() as conn:
            await conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES ('alert_channel_id', ?)",
                (str(channel.id),)
            )
            await conn.commit()
        await interaction.response.send_message(f"Alert channel set to {channel.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Commands(bot))
```

**Step 3: Write bot/client.py**

```python
import discord
from discord.ext import commands
import logging
import config

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
intents.message_content = True

def create_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        logger.info("Bot logged in as %s (id=%s)", bot.user, bot.user.id)
        try:
            guild = discord.Object(id=config.DISCORD_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            logger.info("Synced %d slash commands", len(synced))
        except Exception as e:
            logger.error("Failed to sync commands: %s", e)

    return bot

async def load_cogs(bot: commands.Bot):
    await bot.load_extension("bot.cogs.commands")
    # Additional cogs loaded here as they are built
```

**Step 4: Verify bot starts (needs real Discord token in .env)**

```bash
python3 -c "
import asyncio
import bot.client as bc
bot = bc.create_bot()
print('Bot object created OK:', bot)
"
```

Expected: `Bot object created OK: <Bot id=None>`

**Step 5: Commit**

```bash
git add bot/
git commit -m "feat: Discord bot core — slash commands, embed builders, cog structure"
```

---

## Task 6: Shot Alert + Feedback Modal

**Files:**
- Create: `bot/cogs/alerts.py`

**Step 1: Write bot/cogs/alerts.py**

```python
import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
from pathlib import Path
from bot.embeds import shot_embed
from grapher.shot_graph import generate_shot_graph
import db
import config

logger = logging.getLogger(__name__)

class FeedbackModal(ui.Modal, title="Rate This Shot"):
    flavor_score = ui.TextInput(label="Flavor Score (1-10)", placeholder="8", max_length=2)
    flavor_notes = ui.TextInput(label="Tasting Notes", placeholder="Sweet, chocolate, mild acidity", required=False, style=discord.TextStyle.paragraph)
    bean_name = ui.TextInput(label="Bean Name", placeholder="Ethiopia Yirgacheffe", required=False)
    roaster = ui.TextInput(label="Roaster", placeholder="Blue Bottle", required=False)
    grind_dose_yield = ui.TextInput(label="Grind / Dose (g) / Yield (g)", placeholder="22 / 18.5 / 37.0", required=False)

    def __init__(self, shot_id: str):
        super().__init__()
        self.shot_id = shot_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            score = int(self.flavor_score.value)
            assert 1 <= score <= 10
        except (ValueError, AssertionError):
            await interaction.followup.send("Score must be 1-10.", ephemeral=True)
            return

        dose, yld, grind = None, None, None
        gdystr = self.grind_dose_yield.value.strip()
        if gdystr:
            parts = [p.strip() for p in gdystr.replace(",", "/").split("/")]
            try:
                if len(parts) >= 1: grind = float(parts[0])
                if len(parts) >= 2: dose = float(parts[1])
                if len(parts) >= 3: yld = float(parts[2])
            except ValueError:
                pass

        async with await db.get_db() as conn:
            await conn.execute(
                """INSERT INTO feedback
                   (shot_id, flavor_score, flavor_notes, bean_name, roaster, grind_size, dose_g, yield_g)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (self.shot_id, score, self.flavor_notes.value, self.bean_name.value,
                 self.roaster.value, grind, dose, yld)
            )
            await conn.commit()

        await interaction.followup.send("Feedback saved! Analysis running...", ephemeral=True)
        # Trigger analysis (non-blocking — wired up in Task 8)

class RateShotView(ui.View):
    def __init__(self, shot_id: str):
        super().__init__(timeout=3600)
        self.shot_id = shot_id

    @ui.button(label="Rate This Shot", style=discord.ButtonStyle.primary, emoji="☕")
    async def rate(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_modal(FeedbackModal(self.shot_id))

class Alerts(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.shot_queue: asyncio.Queue = asyncio.Queue()
        self._task = None

    async def cog_load(self):
        self._task = asyncio.create_task(self._process_shots())

    async def cog_unload(self):
        if self._task:
            self._task.cancel()

    async def enqueue_shot(self, event: dict):
        await self.shot_queue.put(event)

    async def _process_shots(self):
        while True:
            event = await self.shot_queue.get()
            try:
                await self._post_shot(event)
            except Exception as e:
                logger.error("Failed to post shot alert: %s", e)

    async def _get_alert_channel(self) -> discord.TextChannel | None:
        async with await db.get_db() as conn:
            async with conn.execute("SELECT value FROM config WHERE key='alert_channel_id'") as cur:
                row = await cur.fetchone()
        if not row:
            ch_id = config.DISCORD_ALERT_CHANNEL_ID
        else:
            ch_id = int(row["value"])
        return self.bot.get_channel(ch_id)

    async def _post_shot(self, event: dict):
        shot = event["shot"]
        shot_id = str(shot["id"])
        channel = await self._get_alert_channel()
        if not channel:
            logger.error("No alert channel configured")
            return

        graph_path = generate_shot_graph(shot)
        async with await db.get_db() as conn:
            await conn.execute("UPDATE shots SET graph_path=? WHERE id=?", (str(graph_path), shot_id))
            await conn.commit()

        embed = shot_embed(shot)
        file = discord.File(graph_path, filename="shot.png")
        embed.set_image(url="attachment://shot.png")
        view = RateShotView(shot_id)
        await channel.send(embed=embed, file=file, view=view)
        logger.info("Shot alert posted for shot %s", shot_id)

        async with await db.get_db() as conn:
            await conn.execute("UPDATE shots SET posted_at=datetime('now') WHERE id=?", (shot_id,))
            await conn.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(Alerts(bot))
```

**Step 2: Commit**

```bash
git add bot/cogs/alerts.py
git commit -m "feat: shot alert cog — Discord embed, PNG attachment, feedback modal"
```

---

## Task 7: Trend Analysis + Heuristics + LLM

**Files:**
- Create: `analysis/trends.py`
- Create: `analysis/heuristics.py`
- Create: `analysis/llm.py`
- Create: `tests/test_analysis.py`

**Step 1: Write failing tests**

```python
# tests/test_analysis.py
import pytest
from analysis.heuristics import diagnose_shot, ExtractionState

def test_under_extraction_by_notes():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 4, "flavor_notes": "very sour and thin", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert result.extraction_state == ExtractionState.UNDER

def test_over_extraction_by_notes():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 4, "flavor_notes": "super bitter and harsh", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert result.extraction_state == ExtractionState.OVER

def test_short_duration_flag():
    shot = {"duration_s": 17}
    feedback = {"flavor_score": 7, "flavor_notes": "ok", "dose_g": 18, "yield_g": 36}
    result = diagnose_shot(shot, feedback)
    assert "channeling" in " ".join(result.flags).lower() or "short" in " ".join(result.flags).lower()

def test_low_brew_ratio_flag():
    shot = {"duration_s": 28}
    feedback = {"flavor_score": 7, "flavor_notes": "ok", "dose_g": 18, "yield_g": 28}  # ratio 1.55
    result = diagnose_shot(shot, feedback)
    assert any("yield" in f.lower() or "ratio" in f.lower() for f in result.suggestions)
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_analysis.py -v
```

**Step 3: Write analysis/heuristics.py**

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class ExtractionState(Enum):
    UNDER = "under"
    OVER = "over"
    NORMAL = "normal"
    UNKNOWN = "unknown"

UNDER_KEYWORDS = {"sour", "acidic", "thin", "watery", "sharp", "bright"}
OVER_KEYWORDS = {"bitter", "harsh", "dry", "astringent", "burnt", "chalky"}

@dataclass
class Diagnosis:
    extraction_state: ExtractionState
    flags: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

def diagnose_shot(shot: dict, feedback: dict) -> Diagnosis:
    notes = (feedback.get("flavor_notes") or "").lower()
    score = feedback.get("flavor_score", 10)
    dose = feedback.get("dose_g")
    yld = feedback.get("yield_g")
    duration = shot.get("duration_s", 30)
    flags, suggestions = [], []

    under_hits = sum(1 for k in UNDER_KEYWORDS if k in notes)
    over_hits = sum(1 for k in OVER_KEYWORDS if k in notes)

    if score < 6 and under_hits > over_hits and under_hits > 0:
        state = ExtractionState.UNDER
        suggestions += ["Try finer grind", "Increase preinfusion duration", "Raise brew temperature by 1°C"]
    elif score < 6 and over_hits >= under_hits and over_hits > 0:
        state = ExtractionState.OVER
        suggestions += ["Try coarser grind", "Reduce extraction time", "Lower brew temperature by 1°C"]
    else:
        state = ExtractionState.NORMAL if score >= 6 else ExtractionState.UNKNOWN

    if duration < 20:
        flags.append("Short shot — possible channeling or grind too coarse")
    if duration > 40:
        flags.append("Long shot — grind may be too fine or dose too high")

    if dose and yld:
        ratio = yld / dose
        if ratio < 1.8:
            suggestions.append("Brew ratio is low — consider increasing yield")
        elif ratio > 2.8:
            suggestions.append("Brew ratio is high — consider decreasing yield or increasing dose")

    return Diagnosis(extraction_state=state, flags=flags, suggestions=suggestions)
```

**Step 4: Write analysis/trends.py**

```python
from dataclasses import dataclass
from typing import Optional
import numpy as np

@dataclass
class TrendReport:
    bean_name: str
    n_shots: int
    score_vs_ratio: Optional[float]   # Pearson r
    score_vs_grind: Optional[float]
    score_vs_dose: Optional[float]
    duration_stddev: Optional[float]
    staleness_slope: Optional[float]  # score change per day since roast
    insufficient_data: bool = False

def _pearson(x: list, y: list) -> Optional[float]:
    if len(x) < 3:
        return None
    try:
        from scipy.stats import pearsonr
        r, _ = pearsonr(x, y)
        return float(r)
    except Exception:
        return None

async def compute_trends(bean_name: str, n_shots: int = 20) -> TrendReport:
    import db
    async with await db.get_db() as conn:
        async with conn.execute(
            """SELECT s.duration_s, f.flavor_score, f.brew_ratio, f.grind_size, f.dose_g, f.roast_date
               FROM feedback f JOIN shots s ON s.id = f.shot_id
               WHERE f.bean_name = ? AND f.flavor_score IS NOT NULL
               ORDER BY s.timestamp DESC LIMIT ?""",
            (bean_name, n_shots)
        ) as cur:
            rows = await cur.fetchall()

    from config import MIN_SHOTS_FOR_RECOMMENDATION
    if len(rows) < MIN_SHOTS_FOR_RECOMMENDATION:
        return TrendReport(bean_name=bean_name, n_shots=len(rows), score_vs_ratio=None,
                           score_vs_grind=None, score_vs_dose=None,
                           duration_stddev=None, staleness_slope=None, insufficient_data=True)

    scores = [r["flavor_score"] for r in rows]
    ratios = [r["brew_ratio"] for r in rows if r["brew_ratio"]]
    grinds = [r["grind_size"] for r in rows if r["grind_size"]]
    doses = [r["dose_g"] for r in rows if r["dose_g"]]
    durations = [r["duration_s"] for r in rows if r["duration_s"]]

    return TrendReport(
        bean_name=bean_name,
        n_shots=len(rows),
        score_vs_ratio=_pearson(ratios, scores[:len(ratios)]) if ratios else None,
        score_vs_grind=_pearson(grinds, scores[:len(grinds)]) if grinds else None,
        score_vs_dose=_pearson(doses, scores[:len(doses)]) if doses else None,
        duration_stddev=float(np.std(durations)) if durations else None,
        staleness_slope=None,  # TODO: implement roast date staleness
    )
```

**Step 5: Write analysis/llm.py**

```python
import json
import logging
from anthropic import AsyncAnthropic
import config

logger = logging.getLogger(__name__)

SAFETY_LIMITS = {
    "pressure": 1.0,
    "temperature": 3.0,
    "duration": 5.0,
    "flow": 0.5,
}

SYSTEM_PROMPT = """You are an expert barista and coffee scientist advising a home espresso enthusiast.
You analyze shot data and provide actionable, specific recommendations.
Always respond with valid JSON matching this schema:
{
  "prose": "2-3 paragraphs of friendly, specific advice",
  "adjustments": [
    {"step_name": "Preinfusion", "field": "duration", "old_value": 8, "new_value": 10}
  ]
}
If no profile adjustments are warranted, set "adjustments" to [].
Keep adjustments conservative and safe."""

def _clamp_adjustments(adjustments: list) -> list:
    safe = []
    for adj in adjustments:
        field = adj.get("field", "")
        limit = SAFETY_LIMITS.get(field)
        if limit is not None:
            delta = abs(float(adj.get("new_value", 0)) - float(adj.get("old_value", 0)))
            if delta > limit:
                logger.warning("Clamping adjustment %s.%s: delta %.2f exceeds limit %.2f",
                               adj.get("step_name"), field, delta, limit)
                continue  # reject, don't clamp to avoid subtle bugs
        safe.append(adj)
    return safe

async def generate_recommendation(
    trend_report,
    diagnosis,
    recent_shots: list,
    current_profile: dict,
) -> dict:
    client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)

    user_content = json.dumps({
        "trend_report": {
            "bean": trend_report.bean_name,
            "n_shots": trend_report.n_shots,
            "score_vs_ratio": trend_report.score_vs_ratio,
            "score_vs_grind": trend_report.score_vs_grind,
            "duration_stddev": trend_report.duration_stddev,
        },
        "diagnosis": {
            "extraction_state": diagnosis.extraction_state.value,
            "flags": diagnosis.flags,
            "suggestions": diagnosis.suggestions,
        },
        "recent_shots": recent_shots[-5:],
        "current_profile": current_profile,
    }, indent=2)

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",  # cost-efficient for structured output
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        result = json.loads(response.content[0].text)
        result["adjustments"] = _clamp_adjustments(result.get("adjustments", []))
        return result
    except Exception as e:
        logger.error("LLM recommendation failed: %s", e)
        # Fallback to heuristic-only
        return {
            "prose": "Based on your recent shots: " + "; ".join(diagnosis.suggestions or ["Keep experimenting!"]),
            "adjustments": [],
        }
```

**Step 6: Run all tests**

```bash
pytest tests/ -v
```

Expected: All pass.

**Step 7: Commit**

```bash
git add analysis/ tests/test_analysis.py
git commit -m "feat: trend analysis, heuristic extraction diagnosis, LLM recommendation synthesis"
```

---

## Task 8: Recommendation Discord Flow + Profile Patcher

**Files:**
- Create: `bot/cogs/recommendations.py`
- Create: `profile_patcher.py`

**Step 1: Write profile_patcher.py**

```python
import json
import logging
import aiohttp
from monitor.fetcher import GaggiaMateClient
import db
import config

logger = logging.getLogger(__name__)

async def patch_profile(adjustments: list) -> dict:
    """Apply adjustments to device profile with snapshot and verification."""
    client = GaggiaMateClient(config.GAGGIA_IP)
    async with aiohttp.ClientSession() as session:
        # Snapshot current profile
        current = await client.get_profile(session)
        async with await db.get_db() as conn:
            await conn.execute(
                "INSERT INTO profiles (name, raw_json, source) VALUES (?,?,?)",
                (current.get("name"), json.dumps(current), "device")
            )
            await conn.commit()

        # Apply adjustments
        patched = json.loads(json.dumps(current))  # deep copy
        steps = {s["name"]: s for s in patched.get("steps", [])}
        for adj in adjustments:
            step = steps.get(adj["step_name"])
            if step and adj["field"] in step:
                step[adj["field"]] = adj["new_value"]

        # PUT and verify
        await client.put_profile(session, patched)
        verified = await client.get_profile(session)

        logger.info("Profile patched and verified: %s", verified.get("name"))
        return {"success": True, "profile": verified}
```

**Step 2: Write bot/cogs/recommendations.py**

```python
import discord
from discord.ext import commands
from discord import ui
import asyncio
import logging
from bot.embeds import recommendation_embed
from profile_patcher import patch_profile
import db

logger = logging.getLogger(__name__)

class ConfirmApplyView(ui.View):
    def __init__(self, adjustments: list, rec_id: int):
        super().__init__(timeout=300)
        self.adjustments = adjustments
        self.rec_id = rec_id

    @ui.button(label="Confirm — Apply Changes", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.defer()
        try:
            result = await patch_profile(self.adjustments)
            async with await db.get_db() as conn:
                await conn.execute(
                    "UPDATE recommendations SET applied=1, applied_at=datetime('now') WHERE id=?",
                    (self.rec_id,)
                )
                await conn.commit()
            await interaction.followup.send("Profile updated on GaggiaMate.")
        except Exception as e:
            await interaction.followup.send(f"Failed to apply profile: {e}", ephemeral=True)
        self.stop()

    @ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()

class ApplyOrSkipView(ui.View):
    def __init__(self, adjustments: list, rec_id: int, channel):
        super().__init__(timeout=3600)
        self.adjustments = adjustments
        self.rec_id = rec_id
        self.channel = channel

    @ui.button(label="Apply Profile Change", style=discord.ButtonStyle.primary)
    async def apply(self, interaction: discord.Interaction, button: ui.Button):
        view = ConfirmApplyView(self.adjustments, self.rec_id)
        await interaction.response.send_message(
            "This will modify your GaggiaMate profile. Are you sure?",
            view=view, ephemeral=True
        )
        self.stop()

    @ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: ui.Button):
        await interaction.response.send_message("Recommendation noted but not applied.", ephemeral=True)
        self.stop()

class Recommendations(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rec_queue: asyncio.Queue = asyncio.Queue()

    async def cog_load(self):
        self._task = asyncio.create_task(self._process_recs())

    async def enqueue_recommendation(self, shot_id: str, bean_name: str, last_shot: dict, profile: dict):
        await self.rec_queue.put((shot_id, bean_name, last_shot, profile))

    async def _process_recs(self):
        while True:
            shot_id, bean_name, last_shot, profile = await self.rec_queue.get()
            try:
                await self._generate_and_post(shot_id, bean_name, last_shot, profile)
            except Exception as e:
                logger.error("Recommendation processing failed: %s", e)

    async def _generate_and_post(self, shot_id, bean_name, last_shot, profile):
        from analysis.trends import compute_trends
        from analysis.heuristics import diagnose_shot
        from analysis.llm import generate_recommendation

        trend = await compute_trends(bean_name)
        if trend.insufficient_data:
            return  # not enough shots yet

        async with await db.get_db() as conn:
            async with conn.execute(
                "SELECT f.*, s.duration_s FROM feedback f JOIN shots s ON s.id=f.shot_id WHERE f.shot_id=?",
                (shot_id,)
            ) as cur:
                fb_row = await cur.fetchone()

        if not fb_row:
            return

        diagnosis = diagnose_shot(last_shot, dict(fb_row))
        rec = await generate_recommendation(trend, diagnosis, [last_shot], profile)

        async with await db.get_db() as conn:
            import json
            cur = await conn.execute(
                "INSERT INTO recommendations (shot_id, recommendation, adjustments_json) VALUES (?,?,?)",
                (shot_id, rec["prose"], json.dumps(rec.get("adjustments", [])))
            )
            rec_id = cur.lastrowid
            await conn.commit()

        from bot.cogs.commands import Commands
        cog = self.bot.get_cog("Commands")
        async with await db.get_db() as conn:
            async with conn.execute("SELECT value FROM config WHERE key='alert_channel_id'") as c:
                row = await c.fetchone()
        ch_id = int(row["value"]) if row else 0
        channel = self.bot.get_channel(ch_id)
        if not channel:
            return

        embed = recommendation_embed(rec["prose"], rec.get("adjustments", []))
        if rec.get("adjustments"):
            view = ApplyOrSkipView(rec["adjustments"], rec_id, channel)
            await channel.send(embed=embed, view=view)
        else:
            await channel.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(Recommendations(bot))
```

**Step 3: Commit**

```bash
git add bot/cogs/recommendations.py profile_patcher.py
git commit -m "feat: recommendation Discord flow, profile patcher with confirm dialog"
```

---

## Task 9: Wire Everything Together (main.py)

**Files:**
- Modify: `main.py`
- Modify: `bot/client.py`

**Step 1: Rewrite main.py**

```python
import asyncio
import argparse
import logging
import signal
import aiohttp
import config
import db
from monitor.fetcher import GaggiaMateClient
from monitor.poller import ShotPoller
from bot.client import create_bot, load_cogs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            "./data/gaggia-bot.log", maxBytes=10*1024*1024, backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

async def run():
    await db.init_db()
    bot = create_bot()
    await load_cogs(bot)
    shot_queue: asyncio.Queue = asyncio.Queue()

    async def on_new_shot(event: dict):
        alerts_cog = bot.get_cog("Alerts")
        if alerts_cog:
            await alerts_cog.enqueue_shot(event)

    client = GaggiaMateClient(config.GAGGIA_IP)
    poller = ShotPoller(client, on_shot=on_new_shot)

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    async with aiohttp.ClientSession():
        poller_task = asyncio.create_task(poller.run())
        bot_task = asyncio.create_task(bot.start(config.DISCORD_BOT_TOKEN))
        stop_task = asyncio.create_task(stop_event.wait())

        done, pending = await asyncio.wait(
            [poller_task, bot_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        poller.stop()
        await bot.close()
        for task in pending:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    logger.info("GaggiaMate bot shut down cleanly.")

async def check_mode():
    await db.init_db()
    print(f"[OK] DB initialized at {config.DB_PATH}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{config.GAGGIA_IP}/api/status",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                print(f"[OK] Device reachable: HTTP {resp.status}")
    except Exception as e:
        print(f"[WARN] Device not reachable: {e}")
    print("[OK] Config loaded — all checks complete")

if __name__ == "__main__":
    import logging.handlers
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        asyncio.run(check_mode())
    else:
        asyncio.run(run())
```

**Step 2: Update bot/client.py to load all cogs**

```python
async def load_cogs(bot: commands.Bot):
    await bot.load_extension("bot.cogs.commands")
    await bot.load_extension("bot.cogs.alerts")
    await bot.load_extension("bot.cogs.recommendations")
```

**Step 3: Run final check**

```bash
python main.py --check
```

Expected: `[OK] Config loaded — all checks complete`

**Step 4: Commit**

```bash
git add main.py bot/client.py
git commit -m "feat: wire poller + bot + cogs into unified async main entrypoint"
```

---

## Task 10: Systemd Service + GitHub Push

**Files:**
- Create: `gaggia-bot.service`
- Create: `install.sh`

**Step 1: Write gaggia-bot.service**

```ini
[Unit]
Description=GaggiaMate Shot Intelligence Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<username>
WorkingDirectory=~/gaggia-bot
EnvironmentFile=~/gaggia-bot/.env
ExecStart=~/gaggia-bot/.venv/bin/python main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Step 2: Write install.sh**

```bash
#!/bin/bash
set -e
sudo cp gaggia-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable gaggia-bot
sudo systemctl start gaggia-bot
echo "Service installed. Check: systemctl status gaggia-bot"
```

**Step 3: Create GitHub repo and push**

```bash
gh repo create gaggia-bot --public --description "GaggiaMate espresso shot intelligence Discord bot" --confirm
git remote add origin git@github.com:<your-github-username>/gaggia-bot.git  # update with actual username
git push -u origin main
```

**Step 4: Commit**

```bash
git add gaggia-bot.service install.sh
git commit -m "feat: systemd service + install script"
```

---

## Execution Priority Order

Given dependencies from PRD Section 13:

```
Task 1 (scaffold) → Task 2 (API audit) → Task 3 (monitor) → Task 4 (grapher)
                                                           ↘
                                        Task 5 (Discord core) → Task 6 (alerts)
                                                                        ↓
                                    Task 7 (analysis) ───────→ Task 8 (rec flow)
                                                                        ↓
                                                        Task 9 (wire main) → Task 10 (deploy)
```

**Tasks 3, 4, 5 can run in parallel after Task 2 completes.**
**Tasks 6, 7 can run in parallel after their respective prerequisites complete.**

## Agent Assignment

| Task | Agent | Model | Notes |
|------|-------|-------|-------|
| 1 (scaffold) | Setup Agent | haiku | Simple file creation |
| 2 (API audit) | API Agent | haiku | curl + document |
| 3 (monitor) | Monitor Agent | sonnet | Async WebSocket logic |
| 4 (grapher) | Grapher Agent | haiku | matplotlib, well-defined |
| 5 (Discord core) | Discord Agent | sonnet | discord.py intricacies |
| 6 (alerts + modal) | Discord Agent | sonnet | UI components |
| 7 (analysis) | Analysis Agent | sonnet | Statistical + LLM code |
| 8 (rec flow) | Discord Agent | haiku | Wiring existing pieces |
| 9 (main) | Integration Agent | sonnet | Signal handling, async |
| 10 (deploy) | DevOps Agent | haiku | systemd + gh CLI |

## QA/QC Gate Before GitHub Push

Each task must pass before merge:
1. `pytest tests/ -v` — all tests green
2. `python main.py --check` — exits 0
3. No `.env` or `data/` files committed (check .gitignore)
4. Code reviewed for: hardcoded credentials, missing error handling, SQL injection (using parameterized queries only)
