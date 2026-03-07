# GaggiaMate WebSocket Events

**Endpoint:** `ws://<device-ip>/ws`
**Protocol:** JSON text frames
**Observed:** 2026-03-07 (machine in Standby mode, ~39°C cold)

## Observed Messages

All messages received during 10-second observation window. Machine was in standby (mode=0), cold start.

```json
{"tp": "evt:status", "ct": 38.98, "tt": 0, "pr": 0.001, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.988, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.992, "tt": 0, "pr": 0.001, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.995, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.997, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.998, "tt": 0, "pr": 0.002, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.999, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 38.999, "tt": 0, "pr": 0.002, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 39, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
{"tp": "evt:status", "ct": 39, "tt": 0, "pr": 0, "fl": 0, "pt": 0, "m": 0, "p": "Example Profile", "puid": "XXXXXXXXXX", "cp": true, "cd": true, "tw": 38, "bta": 0, "bt": 0, "btd": 101, "led": false, "gtd": 24000, "gtv": 18, "gt": 0, "gact": 0, "bw": 0, "cw": 0, "bc": false}
```

## Field Reference

| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `tp` | string | `"evt:status"` | Event type identifier |
| `ct` | float | `38.99` | Current boiler temperature (°C) |
| `tt` | float | `0` | Target temperature (°C); 0 in standby |
| `pr` | float | `0.001` | Current pressure (bar) |
| `pt` | float | `0` | Target pressure (bar) |
| `fl` | float | `0` | Current flow rate (ml/s) |
| `m` | int | `0` | Machine mode (see below) |
| `p` | string | `"Example Profile"` | Selected profile display name |
| `puid` | string | `"XXXXXXXXXX"` | Selected profile ID (short key) |
| `cp` | bool | `true` | Pressure sensor capability available |
| `cd` | bool | `true` | Display dimming capability available |
| `tw` | float | `38` | Target weight (g); 0 if unset |
| `bta` | bool/int | `0` | Volumetric (brew-by-weight) available |
| `bt` | int | `0` | Brew target value |
| `btd` | int | `101` | Brew target duration (ms) |
| `led` | bool | `false` | LED control capability |
| `gtd` | int | `24000` | Grind target duration (ms) |
| `gtv` | int | `18` | Grind target volume (ml) |
| `gt` | int | `0` | Grind target type (0=time, 1=volume) |
| `gact` | int | `0` | Grind active flag |
| `bw` | float | `0` | BLE scale weight (g) |
| `cw` | float | `0` | Current weight |
| `bc` | bool | `false` | BLE scale connected |
| `process` | object\|null | `null` | Shot process state; present during active shot |

## Machine Mode Values (`m` field)

| Value | Label | Description |
|-------|-------|-------------|
| `0` | Standby | Machine idle / not heating |
| `1` | Brew | Pulling espresso shot |
| `2` | Steam | Steaming milk |
| `3` | Water | Dispensing hot water |
| `4` | Grind | Grinding coffee |

## Process Field (during active shot)

When a shot is active, `evt:status` includes a `process` object:

```json
{
  "process": {
    "a": true,    // active — shot is running
    "e": false    // ended — shot has completed
  }
}
```

- `process` is `null` when no shot is active
- `process.a = true` + `m = 1` → shot in progress
- `process.e = true` → shot just ended (transition window)

## Shot Detection Strategy

1. Subscribe to `ws://<device-ip>/ws`
2. Parse each `evt:status` message
3. **Shot START:** `m` transitions to `1` (Brew) **or** `process.a` becomes `true`
4. **Shot END:** `process.e` becomes `true` **or** `m` transitions back to `0` (Standby)
5. After shot end, poll `/api/history/index.bin` to find the new shot record (highest `id`)
6. Fetch `/api/history/{id:06d}.slog` to retrieve full telemetry

## Other Event Types

These event types exist in the JS bundle but were not observed during the audit session:

- `evt:autotune-result` — PID autotune completion
- `evt:ota-progress` — OTA firmware update progress

## WebSocket Frequency

- `evt:status` fires at approximately **1 Hz** (1 message per second)
- Connection is persistent; no ping/pong authentication required
