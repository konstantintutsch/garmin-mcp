# garmin-mcp

> [!NOTE]
> This project is entirely vibe-coded. This line is the only line written by a human in the entire codebase.

A local [MCP](https://modelcontextprotocol.io) server that gives AI assistants **read-only** access to
your [Garmin Connect](https://connect.garmin.com) health and activity data. It is built on the
community [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, so it uses your
normal Garmin account login. There is no official Garmin API key involved.

Everything runs on your machine. Your credentials are only used by `garmin-mcp login`; only session
tokens are stored (`~/.garmin-mcp/garmin_tokens.json`, mode `0600`).

## What you can ask

Activities (runs, rides, swims, strength, ... with splits, laps, HR/power zones, weather, gear, GPS file
export), sleep, heart rate, resting HR, HRV, stress, Body Battery, SpO2, respiration, steps, floors,
intensity minutes, hydration, weight and body composition, blood pressure, training readiness/status,
VO2 max, race predictions, endurance and hill score, lactate threshold, FTP, devices, goals, badges,
and more (about 260 read methods in total).

## Install

Requires macOS/Linux with [uv](https://docs.astral.sh/uv/) (`brew install uv`).

```sh
git clone <this repo> garmin-mcp && cd garmin-mcp
uv sync
uv run garmin-mcp login      # email, password, MFA code if enabled
uv run garmin-mcp status     # verify
```

## Connect it to a client

### Claude Desktop (stdio)

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/garmin-mcp", "garmin-mcp", "serve"]
    }
  }
}
```

### Claude Code / OpenCode / others

```sh
claude mcp add garmin -- uv run --directory /absolute/path/to/garmin-mcp garmin-mcp serve
```

### Local HTTP server

```sh
uv run garmin-mcp serve --transport http --port 8765     # http://127.0.0.1:8765/mcp
```

The HTTP endpoint has **no authentication** and binds to `127.0.0.1` by default. Anything on your machine
can read your Garmin data through it. Don't expose it to a network.

## Tools

Two toolsets (`serve --toolset core|all`):

| Toolset | What you get |
| --- | --- |
| `core` (default) | About 60 curated tools for the common data, plus `garmin_list_methods` and `garmin_call` to discover and run **any** other read method. Keeps the tool list small for clients that struggle with hundreds of tools. |
| `all` | Every read method registered as its own tool (about 260). |

Always available: `get_today` (today's date in your Garmin timezone), `garmin_api_get` (raw GET against any
Garmin Connect API path), and `download_activity` (saves a TCX/GPX/KML/CSV or original FIT zip to
`~/.garmin-mcp/downloads` and returns the path).

Only read methods are exposed. Nothing can create, edit or delete data on your Garmin account.

Large responses (e.g. a full day of per-minute heart rate, or an activity's chart data) are automatically
downsampled to fit `--max-chars` (default 100000), and the result says so; ask for a shorter range to get full
resolution.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GARMIN_MCP_TOKENSTORE` | `~/.garmin-mcp` | Where session tokens live |
| `GARMIN_MCP_DOWNLOAD_DIR` | `<tokenstore>/downloads` | Where `download_activity` writes |
| `GARMIN_IS_CN` | unset | Set to `true` for Garmin China accounts |
| `GARMIN_EMAIL`, `GARMIN_PASSWORD` | unset | Optional: used by `login` instead of prompting, and by the server as a fallback if no tokens exist (accounts without MFA only) |

Tokens refresh automatically. If Garmin rejects them, tools return an error asking you to run
`garmin-mcp login` again. `garmin-mcp logout` deletes the saved tokens.

## Development

```sh
uv run pytest
uv run ruff check . && uv run ruff format .
```

Tests use a fake Garmin client and exercise the real MCP protocol (in-memory and over stdio); they need no
account.

## Notes

- This relies on unofficial endpoints and may break if Garmin changes them. Logging in too often can get you
  rate limited, which is why tokens are reused.
- Not affiliated with Garmin.
