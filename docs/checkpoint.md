# GaggiaMate Bot — Build Checkpoint

**Session:** c181e180-2fcf-4fe1-adfb-ca822bc625d3
**Last updated:** 2026-03-07
**Working directory:** /home/michael/gaggia-bot
**Venv:** /home/michael/gaggia-bot/.venv

## Task Status

| # | Task | Status |
|---|------|--------|
| 1 | Project Scaffold | ✅ Complete |
| 2 | API Audit | ✅ Complete |
| 3 | Shot Monitor (WebSocket + Binary Parser) | 🔄 Next |
| 4 | Graph Generation | ⏳ Pending |
| 5 | Discord Bot Core | ⏳ Pending |
| 6 | Shot Alert + Feedback Modal | ⏳ Pending |
| 7 | Trend Analysis + Heuristics + LLM | ⏳ Pending |
| 8 | Recommendation Flow + Profile Patcher | ⏳ Pending |
| 9 | Wire Main Entrypoint | ⏳ Pending |
| 10 | Systemd Service + GitHub Push | ⏳ Pending |

## CRITICAL API CORRECTIONS (Task 2 findings)

The GaggiaMate API is **binary**, not JSON REST. Plan must use these real schemas:

### WebSocket (ws://192.168.4.253/ws)
- Event type: `evt:status` (NOT `StatusEvent`)
- Mode field: `m` integer (NOT string `mode`)
  - 0=Standby, 1=Brew, 2=Steam, 3=Water, 4=Grind
- Shot active: `process.a == true`
- Shot ended: `process.e == true`
- Current temp: `ct` (°C float)
- Current pressure: `pr` (bar float)
- Profile name: `p` (string)
- Profile ID: `puid` (string key)

### Binary Shot Index: GET /api/history/index.bin
- Magic: `SIDX`, 32-byte header, 128-byte records
- Record: `id` (u32), `timestamp` (u32 unix epoch), `profile_name` (char[32])
- 52 shots on device currently

### Binary Shot Data: GET /api/history/{id:06d}.slog
- Magic: `SHOT`, version 5, 512-byte header
- 250ms sample interval, 13 fields per sample (26 bytes):
  - `t` (ms u32), `tt`/`ct` (temp ÷10 °C), `tp`/`cp` (pressure ÷10 bar)
  - `fl`/`tf`/`pf`/`vf` (flow ÷100 ml/s), `v`/`ev` (volume ÷10 ml)
  - `pr` (pump ratio ÷100), `systemInfo` (bitmask)
- Phase transitions embedded in header

### REST API (no JSON history/profile endpoints exist)
- GET /api/status → `{"mode": 0, "tt": 0, "ct": 40.237}` (minimal)
- GET /api/settings → full device config JSON
- No /api/history (JSON), no /api/profile, no /api/profiles

## Resume Instructions

The plan at docs/plans/2026-03-07-gaggia-bot.md needs updating for binary API.
Next action: Implement Task 3 (Shot Monitor) using:
1. Binary SIDX parser to read shot index
2. Binary SLOG parser to read shot telemetry
3. WebSocket `evt:status` listener, detect shots via `m==1 && process.a` → `process.e==true`
4. Fetch new shots by comparing SIDX against DB

Execute using subagent-driven-development skill from the plan.
