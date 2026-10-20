"""Builds MCP tools from the read-only methods of the `garminconnect` library."""

import inspect
import json
import re
from collections.abc import Callable
from typing import Annotated, Any

from garminconnect import Garmin
from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import config
from .auth import LOGIN_HINT, GarminSession, NotLoggedInError
from .render import render

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
LOCAL_FILE_WRITE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True
)

# Read methods outside the `get_*` family.
EXTRA_READ_METHODS = ("count_activities",)

# Tools registered directly in the default "core" toolset. Every other read method stays
# reachable through `garmin_list_methods` / `garmin_call`.
CORE_METHODS = (
    # profile & daily overview
    "get_user_profile",
    "get_user_summary",
    "get_stats_and_body",
    "get_daily_summaries",
    "get_lifetime_totals",
    "get_user_statistics",
    # activities
    "get_activities",
    "get_activities_by_date",
    "get_last_activity",
    "count_activities",
    "get_activity",
    "get_activity_details",
    "get_activity_splits",
    "get_activity_typed_splits",
    "get_activity_split_summaries",
    "get_activity_hr_in_timezones",
    "get_activity_power_in_timezones",
    "get_activity_weather",
    "get_activity_gear",
    "get_activity_exercise_sets",
    "get_activity_types",
    "get_personal_record",
    "get_progress_summary_between_dates",
    "get_weekly_activity_stats",
    # daily health
    "get_sleep_data",
    "get_heart_rates",
    "get_rhr_day",
    "get_hrv_data",
    "get_stress_data",
    "get_body_battery",
    "get_body_battery_events",
    "get_spo2_data",
    "get_respiration_data",
    "get_steps_data",
    "get_floors",
    "get_intensity_minutes_data",
    "get_hydration_data",
    # body
    "get_body_composition",
    "get_weigh_ins",
    "get_blood_pressure",
    # trends
    "get_daily_steps",
    "get_daily_heart_rate_stats",
    "get_daily_stress_stats",
    "get_sleep_stats_weekly",
    # fitness & performance
    "get_training_readiness",
    "get_training_status",
    "get_max_metrics",
    "get_race_predictions",
    "get_endurance_score",
    "get_hill_score",
    "get_fitnessage_data",
    "get_lactate_threshold",
    "get_cycling_ftp",
    # devices, goals, achievements
    "get_devices",
    "get_device_last_used",
    "get_goals",
    "get_earned_badges",
)


def read_methods() -> dict[str, Callable[..., Any]]:
    """All read-only `Garmin` methods that can be exposed as tools, keyed by name."""
    methods: dict[str, Callable[..., Any]] = {}
    for name, fn in inspect.getmembers(Garmin, inspect.isfunction):
        if not (name.startswith("get_") or name in EXTRA_READ_METHODS):
            continue
        params = inspect.signature(fn).parameters.values()
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
            continue
        methods[name] = fn
    return methods


def _description(name: str, fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) or name.replace("_", " ").capitalize()
    first_paragraph = re.split(r"\n\s*\n", doc.strip())[0]
    text = " ".join(first_paragraph.split())
    return f"{text} (Garmin Connect, read-only. Dates are YYYY-MM-DD.)"


def _relax_annotation(name: str, annotation: Any) -> Any:
    """LLMs pass numeric IDs as JSON numbers; accept them wherever an ID is expected."""
    if name.endswith("_id") and annotation is str:
        return int | str
    return annotation


def _normalise_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: str(v) if k.endswith("_id") and isinstance(v, int) else v for k, v in kwargs.items()}


def _tool_signature(fn: Callable[..., Any]) -> inspect.Signature:
    params = []
    for p in inspect.signature(fn).parameters.values():
        if p.name == "self":
            continue
        if p.name.startswith("_") and p.default is not inspect.Parameter.empty:
            continue  # private options such as `_type` are not part of the public tool
        params.append(p.replace(annotation=_relax_annotation(p.name, p.annotation)))
    return inspect.Signature(params, return_annotation=str)


class Toolbox:
    """Shared state for tool implementations: the Garmin session and output limits."""

    def __init__(self, session: GarminSession, max_chars: int) -> None:
        self.session = session
        self.max_chars = max_chars

    def call(self, name: str, fn: Callable[..., Any], **kwargs: Any) -> Any:
        """Call `fn(garmin, **kwargs)`, translating library errors into `ToolError`."""
        try:
            garmin = self.session.client()
            return fn(garmin, **_normalise_args(kwargs))
        except NotLoggedInError as e:
            raise ToolError(str(e)) from e
        except GarminConnectAuthenticationError as e:
            self.session.reset()
            raise ToolError(f"Garmin session expired or was rejected: {e}. {LOGIN_HINT}") from e
        except GarminConnectTooManyRequestsError as e:
            raise ToolError(f"Garmin rate limit hit, retry later: {e}") from e
        except GarminConnectNotFoundError as e:
            raise ToolError(f"{name}: not found on Garmin Connect ({e})") from e
        except GarminConnectConnectionError as e:
            raise ToolError(f"{name}: Garmin Connect request failed: {e}") from e
        except (ValueError, TypeError) as e:
            raise ToolError(f"{name}: invalid arguments: {e}") from e

    def text(self, obj: Any) -> str:
        return "null" if obj is None else render(obj, self.max_chars)


def _make_tool(box: Toolbox, name: str, method: Callable[..., Any]) -> Callable[..., str]:
    signature = _tool_signature(method)

    def tool(**kwargs: Any) -> str:
        return box.text(box.call(name, method, **kwargs))

    tool.__name__ = name
    tool.__qualname__ = name
    tool.__doc__ = _description(name, method)
    tool.__signature__ = signature  # type: ignore[attr-defined]
    tool.__annotations__ = {p.name: p.annotation for p in signature.parameters.values()}
    tool.__annotations__["return"] = str
    return tool


def register_tools(server: MCPServer, session: GarminSession, toolset: str, max_chars: int) -> int:
    """Register Garmin tools on `server`. Returns the number of tools registered."""
    box = Toolbox(session, max_chars)
    methods = read_methods()
    selected = methods if toolset == "all" else {n: methods[n] for n in CORE_METHODS}

    for name, method in selected.items():
        server.add_tool(
            _make_tool(box, name, method),
            name=name,
            description=_description(name, method),
            annotations=READ_ONLY,
        )
    custom = _register_custom_tools(server, box, methods, include_dispatch=(toolset != "all"))
    return len(selected) + custom


def _register_custom_tools(
    server: MCPServer,
    box: Toolbox,
    methods: dict[str, Callable[..., Any]],
    include_dispatch: bool,
) -> int:
    @server.tool(annotations=READ_ONLY)
    def get_today() -> str:
        """Today's date (YYYY-MM-DD) in the Garmin account's timezone. Use it to resolve
        relative dates such as "yesterday" or "last week" before querying other tools."""
        return box.text(box.call("get_today", lambda g: g.today().isoformat()))

    @server.tool(annotations=READ_ONLY)
    def garmin_api_get(
        path: Annotated[
            str,
            Field(
                description="API path, e.g. /usersummary-service/stats/steps/daily/2026-01-01/2026-01-07"  # noqa: E501
            ),
        ],
        params: Annotated[
            dict[str, str | int | float | bool] | None, Field(description="Query string parameters")
        ] = None,
    ) -> str:
        """Raw GET against the Garmin Connect API for endpoints that have no dedicated tool.
        Read-only; the path must not contain a query string (use `params`)."""
        if not path.startswith("/"):
            raise ToolError("path must start with '/'")
        kwargs = {"params": params} if params else {}
        return box.text(box.call("garmin_api_get", lambda g: g.connectapi(path, **kwargs)))

    @server.tool(annotations=LOCAL_FILE_WRITE)
    def download_activity(
        activity_id: Annotated[int | str, Field(description="Garmin activity ID")],
        format: Annotated[
            str, Field(description="One of: ORIGINAL (zip with the FIT file), TCX, GPX, KML, CSV")
        ] = "TCX",
    ) -> str:
        """Download an activity's raw file (GPS track, sensor data) to the local download
        directory and return its path. Reads from Garmin; only writes a local file."""
        formats = Garmin.ActivityDownloadFormat
        fmt = format.upper()
        if fmt not in formats.__members__:
            raise ToolError(f"format must be one of: {', '.join(formats.__members__)}")
        data = box.call(
            "download_activity",
            lambda g: g.download_activity(str(activity_id), dl_fmt=formats[fmt]),
        )
        target = config.download_dir()
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"activity_{activity_id}.{'zip' if fmt == 'ORIGINAL' else fmt.lower()}"
        path.write_bytes(data)
        return json.dumps({"path": str(path), "bytes": len(data), "format": fmt})

    if not include_dispatch:
        return 3

    @server.tool(annotations=READ_ONLY)
    def garmin_list_methods(
        query: Annotated[
            str | None,
            Field(description="Case-insensitive substring filter, e.g. 'sleep' or 'training'"),
        ] = None,
    ) -> str:
        """List every read-only Garmin Connect data method runnable with `garmin_call`, with
        parameters and description. Use it to discover data without a dedicated tool (golf,
        nutrition, gear, ECG, women's health, calendar, courses, ...)."""
        needle = (query or "").lower()
        rows = []
        for name, fn in methods.items():
            description = _description(name, fn)
            if needle and needle not in name.lower() and needle not in description.lower():
                continue
            parameters = str(_tool_signature(fn)).replace(" -> str", "")
            rows.append({"method": name, "parameters": parameters, "description": description})
        return box.text(rows)

    @server.tool(annotations=READ_ONLY)
    def garmin_call(
        method: Annotated[str, Field(description="Method name from garmin_list_methods")],
        arguments: Annotated[
            dict[str, Any] | None, Field(description="Keyword arguments for the method")
        ] = None,
    ) -> str:
        """Run any read-only Garmin Connect data method by name (see `garmin_list_methods`)."""
        fn = methods.get(method)
        if fn is None:
            raise ToolError(
                f"Unknown method {method!r}. Use garmin_list_methods to discover methods."
            )
        kwargs = _normalise_args(arguments or {})
        try:
            _tool_signature(fn).bind(**kwargs)
        except TypeError as e:
            raise ToolError(f"{method}: {e}. Signature: {_tool_signature(fn)}") from e
        return box.text(box.call(method, fn, **kwargs))

    return 5
