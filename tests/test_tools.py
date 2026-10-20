import asyncio
import json
import os
import sys
from datetime import date

import pytest
from garminconnect import Garmin
from garminconnect.exceptions import GarminConnectAuthenticationError, GarminConnectNotFoundError
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from garmin_mcp.auth import GarminSession, NotLoggedInError
from garmin_mcp.server import build_server
from garmin_mcp.tools import CORE_METHODS, read_methods


class FakeGarmin:
    """Stands in for `Garmin`: records calls, serves canned data."""

    ActivityDownloadFormat = Garmin.ActivityDownloadFormat

    def __init__(self):
        self.calls = []

    def today(self):
        return date(2026, 10, 20)

    def get_sleep_data(self, cdate):
        self.calls.append(("get_sleep_data", cdate))
        return {"date": cdate, "sleepTimeSeconds": 27000}

    def get_activity(self, activity_id):
        self.calls.append(("get_activity", activity_id))
        if activity_id == "404":
            raise GarminConnectNotFoundError("nope")
        return {"activityId": activity_id}

    def get_heart_rates(self, cdate):
        return {"values": [[i, 50] for i in range(50_000)]}

    def connectapi(self, path, **kwargs):
        return {"path": path, **kwargs}

    def download_activity(self, activity_id, dl_fmt):
        return b"<gpx/>"


class FakeSession(GarminSession):
    def __init__(self, garmin=None, error=None):
        super().__init__()
        self.garmin, self.error, self.resets = garmin, error, 0

    def client(self):
        if self.error:
            raise self.error
        return self.garmin

    def reset(self):
        self.resets += 1


def call(server, name, args=None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})

    return asyncio.run(run())


def text(result):
    return result.content[0].text


@pytest.fixture
def garmin():
    return FakeGarmin()


def test_core_methods_exist_in_installed_library():
    assert set(CORE_METHODS) <= set(read_methods())


def test_only_read_methods_are_discovered():
    for name in read_methods():
        assert name.startswith("get_") or name == "count_activities"


def test_core_and_all_toolsets():
    core = asyncio.run(build_server("core", session=FakeSession()).list_tools())
    full = asyncio.run(build_server("all", session=FakeSession()).list_tools())
    core_names = {t.name for t in core}
    full_names = {t.name for t in full}
    assert {"garmin_call", "garmin_list_methods", "get_today", "download_activity"} <= core_names
    assert "garmin_call" not in full_names
    assert len(full_names) > len(core_names) > 50
    assert all(t.annotations.read_only_hint for t in core if t.name.startswith("get_"))


def test_tool_call_passes_arguments_through(garmin):
    result = call(
        build_server(session=FakeSession(garmin)), "get_sleep_data", {"cdate": "2026-10-19"}
    )
    assert not result.is_error
    assert json.loads(text(result)) == {"date": "2026-10-19", "sleepTimeSeconds": 27000}
    assert garmin.calls == [("get_sleep_data", "2026-10-19")]


def test_numeric_ids_are_accepted_and_stringified(garmin):
    result = call(
        build_server(session=FakeSession(garmin)), "get_activity", {"activity_id": 12345678901}
    )
    assert not result.is_error
    assert garmin.calls == [("get_activity", "12345678901")]


def test_today_uses_garmin_timezone(garmin):
    result = call(build_server(session=FakeSession(garmin)), "get_today")
    assert json.loads(text(result)) == "2026-10-20"


def test_large_results_are_downsampled(garmin):
    result = call(
        build_server(max_chars=3000, session=FakeSession(garmin)),
        "get_heart_rates",
        {"cdate": "2026-10-19"},
    )
    assert len(text(result)) <= 3000
    assert "_downsampled" in text(result)


def test_not_found_becomes_tool_error(garmin):
    result = call(build_server(session=FakeSession(garmin)), "get_activity", {"activity_id": 404})
    assert result.is_error
    assert "not found" in text(result)


def test_missing_login_tells_user_how_to_log_in():
    session = FakeSession(error=NotLoggedInError("no tokens. Run `garmin-mcp login` in a terminal"))
    result = call(build_server(session=session), "get_sleep_data", {"cdate": "2026-10-19"})
    assert result.is_error
    assert "garmin-mcp login" in text(result)


def test_rejected_session_is_reset_for_retry(garmin):
    def boom(cdate):
        raise GarminConnectAuthenticationError("401")

    garmin.get_sleep_data = boom
    session = FakeSession(garmin)
    result = call(build_server(session=session), "get_sleep_data", {"cdate": "2026-10-19"})
    assert result.is_error
    assert session.resets == 1


def test_garmin_call_dispatches_and_validates(garmin):
    server = build_server(session=FakeSession(garmin))
    ok = call(
        server, "garmin_call", {"method": "get_sleep_data", "arguments": {"cdate": "2026-10-19"}}
    )
    assert json.loads(text(ok))["sleepTimeSeconds"] == 27000

    unknown = call(
        server, "garmin_call", {"method": "delete_activity", "arguments": {"activity_id": "1"}}
    )
    assert unknown.is_error and "Unknown method" in text(unknown)

    bad_args = call(server, "garmin_call", {"method": "get_sleep_data", "arguments": {"nope": 1}})
    assert bad_args.is_error and "Signature" in text(bad_args)


def test_garmin_list_methods_filters():
    result = call(build_server(session=FakeSession()), "garmin_list_methods", {"query": "golf"})
    names = {row["method"] for row in json.loads(text(result))}
    assert "get_golf_summary" in names
    assert "get_sleep_data" not in names


def test_raw_api_get(garmin):
    server = build_server(session=FakeSession(garmin))
    ok = call(server, "garmin_api_get", {"path": "/x/y", "params": {"a": 1}})
    assert json.loads(text(ok)) == {"path": "/x/y", "params": {"a": 1}}
    assert call(server, "garmin_api_get", {"path": "https://evil.example"}).is_error


def test_download_activity_writes_file(garmin, tmp_path, monkeypatch):
    monkeypatch.setenv("GARMIN_MCP_DOWNLOAD_DIR", str(tmp_path))
    result = call(
        build_server(session=FakeSession(garmin)),
        "download_activity",
        {"activity_id": 7, "format": "gpx"},
    )
    info = json.loads(text(result))
    assert info["path"] == str(tmp_path / "activity_7.gpx")
    assert (tmp_path / "activity_7.gpx").read_bytes() == b"<gpx/>"
    assert call(
        build_server(session=FakeSession(garmin)),
        "download_activity",
        {"activity_id": 7, "format": "exe"},
    ).is_error


def test_stdio_server_end_to_end(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GARMIN")}
    env["GARMIN_MCP_TOKENSTORE"] = str(tmp_path)
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "garmin_mcp", "serve"], env=env
    )

    async def run():
        async with Client(params) as client:
            tools = await client.list_tools()
            result = await client.call_tool("get_today", {})
            return tools, result

    tools, result = asyncio.run(run())
    assert len(tools.tools) > 50
    assert result.is_error
    assert "garmin-mcp login" in text(result)
