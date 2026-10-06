"""The n8n Deterministic Checks expressions give the same results as harness/checks.py.

The corpus is every input the harness's own check tests (tests/unit/test_checks.py) pass to the check
functions, recorded by wrapping them, plus the length strings given to `_length_target` directly (each
replayed at the edges of its allowed range). Each n8n expression is evaluated in Node.js over the whole
corpus in one process and compared field by field with the harness CheckResult.
"""
import inspect
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from harness import checks
from tests.unit import test_checks

WORKFLOW = Path(__file__).resolve().parents[2] / "n8n" / "draftstudio_pipeline.workflow.json"
NODE = shutil.which("node")
RECORDED = ("check_length", "check_key_points", "check_citations", "check_format", "_length_target")


class NodeAvailableTest(unittest.TestCase):
    """The n8n expression tests (this file, test_n8n_quality_gate, test_n8n_research) skip without `node`;
    fail loudly instead, unless the skip is requested with DRAFTSTUDIO_SKIP_NODE_TESTS=1."""

    def test_node_is_installed_for_the_n8n_expression_tests(self):
        if os.environ.get("DRAFTSTUDIO_SKIP_NODE_TESTS") == "1":
            self.skipTest("DRAFTSTUDIO_SKIP_NODE_TESTS=1")
        self.assertIsNotNone(NODE, "node is required to run the n8n expression tests (or set DRAFTSTUDIO_SKIP_NODE_TESTS=1)")


def _assignment(node_name, field):
    node = {n["name"]: n for n in json.loads(WORKFLOW.read_text())["nodes"]}[node_name]
    for a in node["parameters"]["assignments"]["assignments"]:
        if a["name"] == field:
            return a["value"]
    raise KeyError(f"{node_name}.{field}")


def evaluate_many(expression, cases):
    """Evaluate one n8n `={{ ... }}` expression for each case ({json, nodes}) in a single Node process."""
    body = expression.strip()
    assert body.startswith("={{") and body.endswith("}}"), body[:40]
    script = f"""
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const stub = nodes => n => ({{ first: () => ({{ json: nodes[n] }}), last: () => ({{ json: nodes[n] }}),
  isExecuted: Object.prototype.hasOwnProperty.call(nodes, n) }});
const run = ($json, $) => ({body[3:-2]});
console.log(JSON.stringify(cases.map(c => {{
  try {{ return run(c.json, stub(c.nodes)); }} catch (e) {{ return {{ error: String(e) }}; }}
}})));
"""
    out = subprocess.run([NODE, "-e", script], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def _call_args(func):
    """Argument tuples for a test function: () or its parametrize values; None when it needs fixtures."""
    params = list(inspect.signature(func).parameters)
    if not params:
        return [()]
    for mark in getattr(func, "pytestmark", []):
        if mark.name == "parametrize":
            names = mark.args[0]
            names = [n.strip() for n in names.split(",")] if isinstance(names, str) else list(names)
            if names == params:
                return [v if len(names) > 1 else (v,) for v in (getattr(p, "values", p) for p in mark.args[1])]
    return None


def _record_corpus():
    calls = {name: [] for name in RECORDED}
    originals = {name: getattr(checks, name) for name in RECORDED}

    def recorder(name):
        def wrapped(*args):
            calls[name].append(args)
            return originals[name](*args)
        return wrapped

    try:
        for name in RECORDED:
            setattr(checks, name, recorder(name))
        for name, func in inspect.getmembers(test_checks, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            for args in _call_args(func) or []:
                try:
                    func(*args)
                except Exception:  # noqa: BLE001 - only the recorded inputs matter here
                    pass
    finally:
        for name, func in originals.items():
            setattr(checks, name, func)
    return calls


def _jsonable(*values):
    try:
        json.dumps(values)
        return True
    except (TypeError, ValueError):
        return False


def _draft(content):
    return {"output": {"draft": {"content": content}}}


@unittest.skipUnless(NODE, "node is required to evaluate n8n expressions")
class ChecksParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = _record_corpus()

    def compare(self, field, cases, expected):
        self.assertGreater(len(cases), 0)
        got = evaluate_many(_assignment("Deterministic Checks", field), cases)
        for case, mine, theirs in zip(cases, got, expected):
            with self.subTest(case=case):
                self.assertEqual(mine, theirs)

    def test_length_matches_the_harness(self):
        inputs = {json.dumps(a) for a in self.calls["check_length"] if _jsonable(*a) and isinstance(a[0], dict)}
        for (length,) in self.calls["_length_target"]:
            if not _jsonable(length):
                continue
            target = checks._length_target(length)
            sizes = {0, 1, 50, 500, 5000}
            if target:
                unit, low, high = target
                sizes |= {max(low - 1, 0), low, low + 1}
                if high is not None:
                    sizes |= {high - 1, high, high + 1}
            for size in sizes:
                content = ("w " * size) if not target or target[0] == "words" else "x" * size
                inputs.add(json.dumps([{"length": length}, content]))
        args = [json.loads(a) for a in sorted(inputs)]
        self.assertGreater(len(args), 150)
        cases = [{"json": _draft(content), "nodes": {"Build Draft Input": {"brief": brief}}} for brief, content in args]
        self.compare("length_check", cases, [checks.check_length(b, c).as_dict() for b, c in args])

    def test_key_points_match_the_harness(self):
        args = [a for a in self.calls["check_key_points"] if _jsonable(*a) and isinstance(a[0], dict)]
        args += [
            ({"key_points": ["AI", "ROI"]}, "Our AI strategy lifts ROI."),
            ({"key_points": ["AI"]}, "We said; FAIR."),
            ({"key_points": ["Remote work policy", "Q3 2026 deadline"]}, "Remote policies start before the Q3 deadline in 2026."),
            ({"key_points": ["C++ (advanced)"]}, "We cover C++ (advanced) topics."),
        ]
        cases = [{"json": _draft(c), "nodes": {"Build Draft Input": {"brief": b}}} for b, c in args]
        self.compare("key_points_check", cases, [checks.check_key_points(b, c).as_dict() for b, c in args])

    def test_citations_match_the_harness(self):
        args = [a for a in self.calls["check_citations"] if _jsonable(*a)]
        args = [a for a in args if isinstance((a[1] or {}).get("sources") or [], list)]
        args += [
            ("Per user@Example.COM:8080 data.", {"sources": [{"url": "https://user@example.com:8080/x", "title": ""}]}),
            ("See bbc.co.uk today.", {"sources": [{"url": "https://www.bbc.co.uk/news", "title": "News"}]}),
            ("As the BBC reported.", {"sources": [{"url": "https://www.bbc.co.uk/news", "title": "News"}]}),
            ("Data from [::1].", {"sources": [{"url": "http://[::1]:80/a", "title": ""}]}),
            ("Nothing cited.", {"sources": ["https://example.com", None, {"title": "Annual Report"}]}),
        ]
        cases = [{"json": _draft(c), "nodes": {"Build Draft Input": {"sources": (d or {}).get("sources") or []}}} for c, d in args]
        self.compare("citations_check", cases, [checks.check_citations(c, d).as_dict() for c, d in args])

    def test_format_matches_the_harness(self):
        args = [a for a in self.calls["check_format"] if _jsonable(*a) and isinstance(a[0], dict)]
        args += [({"format": "Markdown memo"}, "Intro\n## Heading"), ({"format": "markdown"}, "#NoSpace"), ({"format": None}, "x")]
        cases = [{"json": _draft(c), "nodes": {"Build Draft Input": {"brief": b}}} for b, c in args]
        self.compare("format_check", cases, [checks.check_format(b, c).as_dict() for b, c in args])


if __name__ == "__main__":
    unittest.main()
