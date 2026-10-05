"""All model calls: the provider chain (Groq, then OpenRouter), the daily-quota model fallback,
retries, schema-enforced replies with validation retries, and a capped tool loop."""

import http.client
import json
import math
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from harness import config
from harness.jsonutil import extract_json
from harness.urls import require_safe_base_url

DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
RETRYABLE_CODES = (0, 429, 500, 502, 503, 504)
MIN_CLAMPED_MAX_TOKENS = 1_024
MAX_TOOL_RESULT_CHARS = 6_000
MAX_RETRY_AFTER_SECONDS = 120
_TPM_LIMIT_RE = re.compile(r"limit\s+(\d+),\s*requested\s+(\d+)", re.IGNORECASE)


PROVIDER_FAULT_WORDS = ("model", "decommission", "deprecat", "not found", "does not exist", "access", "tool_use_failed")


class LLMHTTPError(Exception):
    """HTTP failure from a model API. code == 0 means a connection-level error."""

    def __init__(self, code, detail, retry_after=None):
        super().__init__(f"HTTP {code}: {detail[:300]}")
        self.code = code
        self.detail = detail
        self.retry_after = retry_after


class SchemaUnsupported(Exception):
    """A provider/model rejected the response_format we asked for. `key` is "provider:model"."""

    def __init__(self, key, detail):
        super().__init__(f"{key} rejected the requested response_format: {detail[:200]}")
        self.key = key


class ReplyError(Exception):
    """A reply the pipeline cannot use. `raw` is the reply text, saved for debugging."""

    def __init__(self, message, raw=""):
        super().__init__(message)
        self.raw = raw


class TruncatedReply(ReplyError):
    pass


class SchemaValidationError(ReplyError):
    pass


class InvalidGeneration(ReplyError):
    """The provider rejected the model's own output as invalid JSON (Groq: json_validate_failed).

    `raw` is the failed generation; `provider_message` is the provider's own explanation."""

    def __init__(self, message, raw="", provider_message=""):
        super().__init__(message, raw)
        self.provider_message = provider_message


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str  # sticky: becomes fallback_model after a daily-quota 429
    fallback_model: str | None = None


def build_messages(system, user):
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validation_errors(data, schema):
    """Up to five readable schema violations, e.g. "$.score: 'x' is not of type 'integer'"."""
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"$.{'.'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors][:5]


def openrouter_configured(env):
    key = env.get("OPENROUTER_API_KEY", "")
    return bool(key) and not key.startswith("your-") and bool(env.get("OPENROUTER_PRIMARY_MODEL"))


def http_post(base_url, api_key, payload, timeout=300, opener=None):
    """POST one chat completion. Raises LLMHTTPError for HTTP, connection and non-JSON failures."""
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "DraftStudio-harness/1.0"},
    )
    # Unredirected: urllib copies req.headers to a redirect target, which must never receive the key.
    req.add_unredirected_header("Authorization", "Bearer " + api_key)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        retry_after = _seconds(err.headers.get("Retry-After") if err.headers else None)
        try:
            detail = err.read().decode(errors="replace")[:20_000]
        except (http.client.HTTPException, OSError) as read_err:
            detail = f"unreadable error body ({type(read_err).__name__})"
        finally:
            err.close()
        raise LLMHTTPError(err.code, detail, retry_after) from err
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError, ValueError) as err:
        raise LLMHTTPError(0, f"{type(err).__name__}: {err}") from err  # ValueError covers JSONDecodeError


def _seconds(value):
    """A Retry-After header as seconds: None unless a finite, non-negative number; at most 120."""
    try:
        seconds = float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP-date Retry-After: use exponential backoff instead
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _clamped_budget(detail, budget):
    """For "Request too large ... Limit L, Requested R", a smaller max_tokens that fits, else None."""
    match = _TPM_LIMIT_RE.search(detail)
    if not match:
        return None
    limit, requested = int(match.group(1)), int(match.group(2))
    smaller = budget - (requested - limit) - 256
    return smaller if MIN_CLAMPED_MAX_TOKENS <= smaller < budget else None


def _error_field(detail, field):
    try:
        return str(json.loads(detail)["error"].get(field) or "")
    except (ValueError, KeyError, TypeError, AttributeError):
        return ""


class LLMClient:
    """Chat client for one pipeline run. Model and provider switches are sticky for the rest of the run."""

    def __init__(self, env, post=None, sleep=time.sleep, log=print):
        self.env = env
        self.post = post or http_post
        self.sleep = sleep
        self.log = log
        self.primary_model = env["GROQ_PRIMARY_MODEL"]
        self.providers = [
            Provider("groq", env["GROQ_BASE_URL"], env["GROQ_API_KEY"], self.primary_model, env.get("GROQ_FALLBACK_MODEL") or None)
        ]
        if openrouter_configured(env):
            self.providers.append(
                Provider(
                    "openrouter",
                    env.get("OPENROUTER_BASE_URL") or DEFAULT_OPENROUTER_BASE_URL,
                    env["OPENROUTER_API_KEY"],
                    env["OPENROUTER_PRIMARY_MODEL"],
                )
            )
        self._current = 0
        self.schema_mode = {}  # "provider:model" -> "json_schema" | "json_object"

    @property
    def provider(self):
        return self.providers[self._current]

    @property
    def active_model(self):
        return self.provider.model

    @property
    def fallback_model_used(self):
        """The Groq model that took over after a daily-quota 429, or None."""
        model = self.providers[0].model
        return None if model == self.primary_model else model

    @property
    def fallback_provider_used(self):
        return self.provider.name if self._current else None

    # -- one completion -------------------------------------------------------------
    def complete(self, messages, max_tokens, *, response_format=None, tools=None, reasoning_effort=None, prepare=None):
        """One chat completion, moving down the provider chain when a provider fails.

        `prepare(provider) -> (messages, response_format, mode)`, when given, builds the request for whichever
        provider is being tried, so a mid-call switch never reuses another provider's response format.
        Returns {content, message, finish_reason, usage, seconds, model, provider, mode}.
        """
        started = time.time()
        mode = None
        while True:
            provider = self.provider
            if prepare:
                messages, response_format, mode = prepare(provider)
            try:
                body, model = self._complete_on(provider, messages, max_tokens, response_format, tools, reasoning_effort)
                break
            except LLMHTTPError as err:
                # A request the provider rejected as malformed would fail anywhere: no switch. A complaint about
                # the provider's own setup (retired or unknown model, access) is not the request's fault.
                low = err.detail.lower()
                if err.code in (400, 422) and not any(word in low for word in PROVIDER_FAULT_WORDS):
                    raise
                if self._current + 1 == len(self.providers):
                    raise
                self._current += 1
                self.log(f"    {provider.name} unavailable ({err}); switching to {self.provider.name} for the rest of the run")
        choice = body["choices"][0]
        message = choice.get("message") or {}
        return {
            "content": message.get("content") or "",
            "message": message,
            "finish_reason": choice.get("finish_reason"),
            "usage": body.get("usage") or {},
            "seconds": round(time.time() - started, 1),
            "model": model,
            "provider": provider.name,
            "mode": mode,
        }

    def _complete_on(self, provider, messages, max_tokens, response_format, tools, reasoning_effort):
        """Call one provider: transient-error retries, the daily-quota model fallback and the 413 clamp."""
        require_safe_base_url(provider.base_url)
        budget, clamped, retries = max_tokens, False, 0
        while True:
            model = provider.model
            payload = {"model": model, "messages": messages, "max_tokens": budget, "temperature": 0.6}
            if response_format:
                payload["response_format"] = response_format
            if tools:
                payload["tools"] = tools
            if reasoning_effort and model.startswith("openai/gpt-oss"):
                payload["reasoning_effort"] = reasoning_effort
            try:
                body = self.post(provider.base_url, provider.api_key, payload)
                if not isinstance(body, dict) or not body.get("choices"):
                    raise LLMHTTPError(502, "response without choices: " + json.dumps(body)[:300])
                return body, model
            except LLMHTTPError as err:
                low = err.detail.lower()
                if err.code == 429 and ("tokens per day" in low or "requests per day" in low):
                    if provider.fallback_model and model != provider.fallback_model:
                        self.log(f"    {model} hit its daily token quota, falling back to {provider.fallback_model}")
                        provider.model = provider.fallback_model
                        continue
                    raise
                if err.code == 400 and "json_validate_failed" in low:
                    raise InvalidGeneration(
                        f"{provider.name}:{model} rejected its own reply as invalid JSON",
                        _error_field(err.detail, "failed_generation"),
                        _error_field(err.detail, "message")[:300],
                    ) from err
                if err.code == 400 and response_format and any(
                    word in low for word in ("response_format", "json_schema", "json_object", "json mode")
                ):
                    raise SchemaUnsupported(f"{provider.name}:{model}", err.detail) from err
                if err.code == 413 and not clamped:
                    smaller = _clamped_budget(err.detail, budget)
                    if smaller:
                        self.log(f"    request too large for {model}'s rate limit; retrying with max_tokens={smaller}")
                        budget, clamped = smaller, True
                        continue
                retryable = err.code in RETRYABLE_CODES or (err.code == 400 and "tool_use_failed" in low)
                if not retryable or retries == 4:
                    raise
                retries += 1
                wait = err.retry_after or 2**retries
                self.log(f"    {err}; retrying in {wait:.0f}s")
                self.sleep(wait)

    # -- structured output ------------------------------------------------------------
    @staticmethod
    def _accumulate(meta, res, mode):
        meta["provider"] = res["provider"]
        meta["model"] = res["model"]
        meta["seconds"] = round(meta["seconds"] + res["seconds"], 1)
        meta["schema_enforced"] = mode == "json_schema"
        meta["finish_reasons"].append(res["finish_reason"])
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            meta["usage"][key] += res["usage"].get(key) or 0

    @staticmethod
    def _parse(text):
        """Return (data, used_extract_json, error). Strict json.loads first; extract_json is the last resort."""
        try:
            data, used_extract = json.loads(text), False
        except json.JSONDecodeError:
            try:
                data, used_extract = extract_json(text), True
            except ValueError as err:  # json.JSONDecodeError is a ValueError too
                return None, False, f"reply was not valid JSON ({err})"
        if not isinstance(data, dict):
            return None, used_extract, "reply must be a JSON object"
        return data, used_extract, None

    def chat_structured(self, messages, schema, name, max_tokens, reasoning_effort=None, max_validation_retries=2):
        """Return (data, meta) where data validates against `schema`.

        Asks for json_schema output; a provider/model that rejects it switches to JSON mode with the schema
        in the prompt (remembered per provider and model). Invalid replies are retried with the errors fed
        back, at most `max_validation_retries` times; a truncated reply is retried once with 1.5x the budget,
        never above config.MAX_COMPLETION_TOKENS.
        """
        messages = list(messages)
        meta = {
            "provider": self.provider.name,
            "model": self.active_model,
            "seconds": 0.0,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "schema_enforced": False,
            "validation_retries": 0,
            "finish_reasons": [],
            "used_extract_json": False,
        }
        budget, raised_budget = max_tokens, False
        while True:
            def prepare(provider, messages=messages):
                # OpenRouter's json_schema mode flattens gpt-oss output to one line (no newlines survive), so it
                # defaults to JSON mode plus local validation; Groq keeps json_schema.
                default_mode = "json_object" if provider.name == "openrouter" else "json_schema"
                mode = self.schema_mode.get(f"{provider.name}:{provider.model}", default_mode)
                if mode == "json_schema":
                    return messages, {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": False}}, mode
                schema_note = "Return one JSON object matching this JSON Schema:\n" + json.dumps(schema)
                return messages + [{"role": "user", "content": schema_note}], {"type": "json_object"}, mode

            started = time.time()
            try:
                res = self.complete(messages, budget, reasoning_effort=reasoning_effort, prepare=prepare)
            except SchemaUnsupported as err:
                if self.schema_mode.get(err.key) == "json_object":
                    raise
                self.schema_mode[err.key] = "json_object"
                self.log(f"    {err.key} does not accept json_schema; using JSON mode with local validation")
                continue
            except InvalidGeneration as err:
                meta["finish_reasons"].append("invalid_generation")
                meta["seconds"] = round(meta["seconds"] + time.time() - started, 1)  # the rejected call's tokens are unknown
                meta["provider"], meta["model"] = self.provider.name, self.active_model
                raw, errors = err.raw, []
                if raw:  # name the real problems in the failed generation
                    data, _, error = self._parse(raw)
                    errors = [error] if error else validation_errors(data, schema)
                if not errors:
                    errors = [err.provider_message or str(err)]
            else:
                self._accumulate(meta, res, res["mode"])
                raw = res["content"]
                if res["finish_reason"] == "length":
                    if raised_budget or budget >= config.MAX_COMPLETION_TOKENS:
                        raise TruncatedReply(f"reply truncated at {budget} tokens", raw)
                    budget, raised_budget = min(int(budget * 1.5), config.MAX_COMPLETION_TOKENS), True
                    self.log(f"    reply truncated; retrying once with max_tokens={budget}")
                    continue
                data, used_extract, error = self._parse(raw)
                if used_extract:
                    meta["used_extract_json"] = True
                    self.log("    reply was not clean JSON; recovered it with extract_json")
                errors = [error] if error else validation_errors(data, schema)
                if not errors:
                    return data, meta
            if meta["validation_retries"] >= max_validation_retries:
                raise SchemaValidationError("; ".join(errors), raw)
            meta["validation_retries"] += 1
            self.log(f"    reply failed validation ({errors[0]}); retry {meta['validation_retries']}/{max_validation_retries}")
            feedback = {
                "role": "user",
                "content": "Your reply failed validation: " + "; ".join(errors) + ". Return the corrected JSON object only.",
            }
            messages = messages + ([{"role": "assistant", "content": raw}] if raw else []) + [feedback]

    # -- tool loop --------------------------------------------------------------------
    def chat_with_tools(self, messages, tools, run_tool, max_calls, max_tokens, reasoning_effort=None):
        """Let the model call tools until it answers or the budget is spent.

        Returns (messages, final, meta): the transcript including tool turns and the final answer, the last
        completion, and {"tool_calls", "seconds", "usage"}. Once `max_calls` tools have run, tools are no
        longer offered; after max_calls + 2 turns the loop stops even if the model keeps asking.
        """
        messages = list(messages)
        meta = {"tool_calls": [], "seconds": 0.0, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, "truncated_turns": 0}
        calls = 0
        for _ in range(max_calls + 2):
            res = self.complete(messages, max_tokens, tools=tools if calls < max_calls else None, reasoning_effort=reasoning_effort)
            meta["seconds"] = round(meta["seconds"] + res["seconds"], 1)
            for key in meta["usage"]:
                meta["usage"][key] += res["usage"].get(key) or 0
            requested = res["message"].get("tool_calls") or []
            if not requested:
                break
            truncated = res["finish_reason"] == "length"
            if truncated:  # the arguments are cut off; the turn spends tool budget so the loop cannot spin on it
                meta["truncated_turns"] += 1
                calls += 1
                self.log(f"    tool-call turn truncated at max_tokens={max_tokens}")
            messages.append({"role": "assistant", "content": res["content"], "tool_calls": requested})
            for call in requested:
                function = call.get("function") or {}
                name = function.get("name", "")
                if truncated:
                    result = "error: your tool call was cut off; answer with the evidence you have"
                elif calls >= max_calls:
                    result = "error: tool budget exhausted; answer with the evidence you have"
                else:
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                        if not isinstance(args, dict):
                            raise ValueError("arguments must be a JSON object")
                    except ValueError as err:  # json.JSONDecodeError is a ValueError too
                        result = f"error: invalid tool arguments ({err})"
                    else:
                        calls += 1
                        self.log(f"    tool {name}({json.dumps(args)[:80]})")
                        result = str(run_tool(name, args))
                        meta["tool_calls"].append({"name": name, "args": args, "ok": not result.startswith("error:")})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": result[:MAX_TOOL_RESULT_CHARS]})
        messages.append({"role": "assistant", "content": res["content"]})
        return messages, res, meta
