import json
from datetime import date

from garmin_mcp.render import render


def test_small_payload_is_untouched_compact_json():
    assert render({"a": [1, 2], "d": date(2026, 1, 2)}, 1000) == '{"a":[1,2],"d":"2026-01-02"}'


def test_long_lists_are_downsampled_to_fit():
    payload = {"hr": [[i, 60 + i % 40] for i in range(5000)], "name": "run"}
    text = render(payload, 5000)
    out = json.loads(text)
    assert len(text) <= 5000
    assert out["name"] == "run"
    assert "_downsampled" in out["hr"]
    assert out["hr"]["items"][0] == [0, 60]
    assert out["hr"]["items"][-1] == [4999, 60 + 4999 % 40]


def test_unshrinkable_payload_is_hard_truncated():
    out = json.loads(render({"blob": "x" * 10_000}, 500))
    assert "_truncated" in out
    assert len(out["text"]) == 500
