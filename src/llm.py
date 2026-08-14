"""
The one place model calls happen.

Every extractor and the ambiguity-resolution pass go through `LLM.complete()` /
`LLM.complete_json()`. Nothing else in the codebase imports the Anthropic SDK.
Centralizing here buys three things the demo depends on:

1. **Per-call accounting.** Tokens, cost, latency, and which model *tier* ran are
   recorded into `PipelineMetrics`, so the dashboard can show a real cost profile
   and defend the tiered-model design.
2. **A tiered model policy.** A cheap, fast model does per-format extraction; a
   stronger model is reserved for the ambiguity-resolution pass. Callers ask for
   a *tier*, not a model string, so the policy lives in one table.
3. **A disk replay cache.** Responses are cached keyed on `(model, request)`.
   The corpus eval and the demo replay from that cache, so `make eval` runs
   offline and reproducibly with no API key. Recording new responses is behind an
   explicit mode, never the default.

Model tiers (see `ModelTier`): the "stronger" tier is Sonnet, not Opus — for a
reference implementation the ambiguity pass doesn't need Opus, and keeping the
expensive tier off the hot path is exactly the cost discipline this project is
arguing for. Change `TIER_MODELS` in one place to re-tune.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .schema import PipelineMetrics


# --------------------------------------------------------------------------
# Model policy
# --------------------------------------------------------------------------

class ModelTier(str, Enum):
    """Callers pick a tier; the tier -> model mapping lives in one table."""
    FAST = "fast"        # per-format extraction, classification — high volume
    STRONG = "strong"    # ambiguity resolution, cross-artifact conflicts — rare


TIER_MODELS: dict[ModelTier, str] = {
    ModelTier.FAST: "claude-haiku-4-5",
    ModelTier.STRONG: "claude-sonnet-5",
}

# USD per 1M tokens, (input, output). Used to turn usage into a cost figure.
# Keep in sync with whatever models TIER_MODELS points at.
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
}


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


# --------------------------------------------------------------------------
# Cache modes
# --------------------------------------------------------------------------

class LLMMode(str, Enum):
    REPLAY = "replay"    # cache only; a miss is an error (the default — offline, safe)
    RECORD = "record"    # cache hit -> replay; miss -> live call + write to cache
    LIVE = "live"        # always call live; never read or write the cache


def _mode_from_env() -> LLMMode:
    return LLMMode(os.environ.get("LLM_MODE", "replay").lower())


class LLMCacheMiss(RuntimeError):
    """Raised in REPLAY mode when a request isn't in the cache.

    The corpus eval is supposed to run entirely from committed cache fixtures. A
    miss means either the corpus/prompts changed or the cache was never recorded
    for this lead — re-record with LLM_MODE=record and a live key.
    """


# --------------------------------------------------------------------------
# Result envelope
# --------------------------------------------------------------------------

@dataclass
class LLMResult:
    text: str
    model: str
    tier: ModelTier
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    cache_hit: bool

    def json(self) -> Any:
        """Parse the response text as JSON. Extractors that requested a schema
        use this; it raises if the model returned non-JSON."""
        return json.loads(self.text)


@dataclass
class _CallRecord:
    tier: ModelTier
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    cache_hit: bool


# --------------------------------------------------------------------------
# The wrapper
# --------------------------------------------------------------------------

class LLM:
    """Stateful per-pipeline-run model client.

    Construct one per lead (or per run) with the lead's `PipelineMetrics`; every
    call updates it. The Anthropic client is created lazily, so nothing needs an
    API key unless a live call actually happens.
    """

    def __init__(
        self,
        metrics: PipelineMetrics | None = None,
        *,
        mode: LLMMode | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.metrics = metrics if metrics is not None else PipelineMetrics()
        self.mode = mode or _mode_from_env()
        self.cache_dir = Path(
            cache_dir or os.environ.get("LLM_CACHE_DIR", "cache/llm")
        )
        self.calls: list[_CallRecord] = []
        self._client: Any = None  # lazily constructed anthropic.Anthropic

    # -- public API --------------------------------------------------------

    def complete(
        self,
        tier: ModelTier,
        *,
        system: str,
        user: str,
        max_tokens: int = 4096,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        """One request/response. `schema`, if given, constrains the output to
        that JSON Schema via structured outputs (supported on both tiers)."""
        model = TIER_MODELS[tier]
        request = self._build_request(model, system, user, max_tokens, schema)
        key = _request_key(request)

        cached = None if self.mode is LLMMode.LIVE else self._read_cache(key)
        if cached is not None:
            result = self._result_from_cache(tier, model, cached, cache_hit=True)
        else:
            if self.mode is LLMMode.REPLAY:
                raise LLMCacheMiss(
                    f"No cached response for {model} (key {key[:12]}). "
                    "Record it with LLM_MODE=record and a live ANTHROPIC_API_KEY, "
                    "or check that prompts/corpus haven't drifted from the cache."
                )
            payload = self._call_live(request)
            if self.mode is LLMMode.RECORD:
                self._write_cache(key, payload)
            result = self._result_from_cache(tier, model, payload, cache_hit=False)

        self._account(result)
        return result

    def complete_json(
        self,
        tier: ModelTier,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> Any:
        """Convenience wrapper: constrain to `schema` and return parsed JSON."""
        return self.complete(
            tier, system=system, user=user, max_tokens=max_tokens, schema=schema
        ).json()

    def tier_usage(self) -> dict[str, int]:
        """How many calls ran on each tier — logged per lead so the demo can show
        that the expensive tier is used sparingly."""
        out: dict[str, int] = {t.value: 0 for t in ModelTier}
        for c in self.calls:
            out[c.tier.value] += 1
        return out

    # -- request construction ---------------------------------------------

    @staticmethod
    def _build_request(
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if schema is not None:
            request["output_config"] = {
                "format": {"type": "json_schema", "schema": schema}
            }
        return request

    # -- live call ---------------------------------------------------------

    def _client_or_create(self) -> Any:
        if self._client is None:
            import anthropic  # imported lazily so the SDK/key aren't needed offline

            self._client = anthropic.Anthropic()
        return self._client

    def _call_live(self, request: dict[str, Any]) -> dict[str, Any]:
        client = self._client_or_create()
        t0 = time.perf_counter()
        resp = client.messages.create(**request)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        return {
            "text": text,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "latency_ms": latency_ms,
            "stop_reason": resp.stop_reason,
        }

    # -- cache -------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> dict[str, Any] | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_cache(self, key: str, payload: dict[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(key).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _result_from_cache(
        self, tier: ModelTier, model: str, payload: dict[str, Any], *, cache_hit: bool
    ) -> LLMResult:
        return LLMResult(
            text=payload["text"],
            model=model,
            tier=tier,
            input_tokens=payload["input_tokens"],
            output_tokens=payload["output_tokens"],
            latency_ms=payload["latency_ms"],
            cost_usd=_cost_usd(model, payload["input_tokens"], payload["output_tokens"]),
            cache_hit=cache_hit,
        )

    # -- accounting --------------------------------------------------------

    def _account(self, result: LLMResult) -> None:
        self.calls.append(_CallRecord(
            tier=result.tier,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=result.latency_ms,
            cost_usd=result.cost_usd,
            cache_hit=result.cache_hit,
        ))
        self.metrics.model_calls += 1
        self.metrics.total_tokens += result.input_tokens + result.output_tokens
        self.metrics.cost_usd = round(self.metrics.cost_usd + result.cost_usd, 6)
        self.metrics.extraction_ms += result.latency_ms


# --------------------------------------------------------------------------
# Cache key
# --------------------------------------------------------------------------

def _request_key(request: dict[str, Any]) -> str:
    """Stable hash of the request. Sorted keys so serialization is deterministic
    — an unstable key silently misses the cache on every run."""
    blob = json.dumps(request, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
