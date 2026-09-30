import importlib.util
import io
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
ENV_TEXT = "\n".join([
    "GROQ_API_KEY=groq-key",
    "GROQ_BASE_URL=https://groq.test/v1",
    "GROQ_PRIMARY_MODEL=llama-primary",
    "GROQ_FALLBACK_MODEL=groq-fallback",
    "OPENROUTER_API_KEY=or-key",
    "OPENROUTER_BASE_URL=https://or.test/v1",
    "OPENROUTER_PRIMARY_MODEL=or-model",
])


def _load_harness(env_text=ENV_TEXT):
    spec = importlib.util.spec_from_file_location("run_pipeline_under_test", REPO / "harness" / "run_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(Path, "read_text", return_value=env_text):
        spec.loader.exec_module(module)
    return module


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(text):
    return _Resp(json.dumps({"choices": [{"message": {"content": text}}], "usage": {}}).encode())


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(b"forbidden"))


class ProviderFallbackTests(unittest.TestCase):
    def setUp(self):
        self.h = _load_harness()
        self.calls = []

    def _urlopen(self, responses):
        def fake(req, timeout=None):
            self.calls.append((req.full_url, json.loads(req.data)["model"]))
            r = responses(req.full_url)
            if isinstance(r, Exception):
                raise r
            return r
        return fake

    def test_groq_success_does_not_touch_openrouter(self):
        with mock.patch("urllib.request.urlopen", self._urlopen(lambda u: _ok("groq"))):
            out = self.h.chat("s", "u", 10)
        self.assertEqual(out["content"], "groq")
        self.assertTrue(all("groq.test" in u for u, _ in self.calls))
        self.assertIsNone(self.h.FALLBACK_PROVIDER)

    def test_groq_region_block_switches_to_openrouter_and_sticks(self):
        responses = lambda u: _http_error(403) if "groq.test" in u else _ok("openrouter")
        with mock.patch("urllib.request.urlopen", self._urlopen(responses)):
            first = self.h.chat("s", "u", 10)
            second = self.h.chat("s", "u", 10)
        self.assertEqual((first["content"], first["model"]), ("openrouter", "or-model"))
        self.assertEqual(second["content"], "openrouter")
        self.assertEqual(self.h.FALLBACK_PROVIDER, "openrouter")
        groq_calls = [c for c in self.calls if "groq.test" in c[0]]
        self.assertEqual(len(groq_calls), 1)  # sticky: the second call skips Groq

    def test_without_openrouter_key_the_groq_error_propagates(self):
        h = _load_harness(ENV_TEXT.replace("OPENROUTER_API_KEY=or-key", "OPENROUTER_API_KEY=your-openrouter-api-key-here"))
        with mock.patch("urllib.request.urlopen", self._urlopen(lambda u: _http_error(403))):
            with self.assertRaises(urllib.error.HTTPError):
                h.chat("s", "u", 10)

    def test_quoted_env_values_are_unquoted(self):
        h = _load_harness(ENV_TEXT.replace("OPENROUTER_API_KEY=or-key", 'OPENROUTER_API_KEY="or-key"'))
        self.assertEqual(h.ENV["OPENROUTER_API_KEY"], "or-key")

    def test_both_providers_failing_raises(self):
        with mock.patch("urllib.request.urlopen", self._urlopen(lambda u: _http_error(403))):
            with self.assertRaises(urllib.error.HTTPError):
                self.h.chat("s", "u", 10)


if __name__ == "__main__":
    unittest.main()
