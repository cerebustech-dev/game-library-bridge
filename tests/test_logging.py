import json
import logging

from game_library_bridge.logging_setup import JsonFormatter, TextFormatter


def make_record(**extra):
    record = logging.LogRecord(
        name="glb.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="something happened", args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_emits_parseable_line_with_extras():
    line = JsonFormatter().format(make_record(count=42, source="steam"))
    payload = json.loads(line)

    assert payload["message"] == "something happened"
    assert payload["level"] == "info"
    assert payload["logger"] == "glb.test"
    assert payload["count"] == 42
    assert payload["source"] == "steam"
    assert payload["ts"].startswith("20")


def test_text_formatter_appends_extras():
    formatter = TextFormatter("%(levelname)s %(name)s: %(message)s")
    line = formatter.format(make_record(count=42))

    assert "something happened" in line
    assert "count=42" in line
