"""MCP server construction."""

from mcp.server.mcpserver import MCPServer

from . import __version__, config
from .auth import GarminSession
from .tools import register_tools

INSTRUCTIONS = """\
Read-only access to the user's Garmin Connect account: activities, sleep, heart rate, HRV,
stress, Body Battery, SpO2, steps, body composition, training status/readiness and more.

- Dates are YYYY-MM-DD. Call get_today first to resolve relative dates.
- To find an activity, use get_activities_by_date or get_activities, then pass its activityId
  to the get_activity_* tools.
- Prefer date-range / summary tools over per-day tools when looking at trends.
- Large results are downsampled automatically; request a shorter date range for full detail.
- If a tool reports the session is missing or expired, tell the user to run `garmin-mcp login`.
"""


def build_server(toolset: str = "core", max_chars: int = config.DEFAULT_MAX_CHARS) -> MCPServer:
    server = MCPServer("garmin", version=__version__, instructions=INSTRUCTIONS)
    register_tools(server, GarminSession(), toolset, max_chars)
    return server
