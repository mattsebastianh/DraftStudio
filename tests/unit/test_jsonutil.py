import pytest

from harness.jsonutil import extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_with_prose():
    text = 'Here you go:\n```json\n{"a": {"b": 2}}\n```\nthanks'
    assert extract_json(text) == {"a": {"b": 2}}


def test_raw_newline_inside_string_is_escaped():
    assert extract_json('{"content": "line1\nline2"}') == {"content": "line1\nline2"}


def test_no_json_raises():
    with pytest.raises(ValueError):
        extract_json("no braces here")


def test_unbalanced_raises():
    with pytest.raises(ValueError):
        extract_json('{"a": 1')


def test_extract_json_ignores_braces_inside_strings():
    assert extract_json('Here: {"draft": {"content": "use } and { here"}} done') == {"draft": {"content": "use } and { here"}}
    assert extract_json('{"a": "quote \\" } still inside"}') == {"a": 'quote " } still inside'}


def test_extract_json_keeps_code_fences_inside_strings():
    reply = 'Sure:\n```json\n{"content": "Use:\\n```python\\nprint(1)\\n```\\nDone"}\n```'
    assert extract_json(reply) == {"content": "Use:\n```python\nprint(1)\n```\nDone"}
