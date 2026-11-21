"""Provider-neutral LLM router.

Every agent call goes through ``call_structured`` / ``call_text`` here, so:

* each agent's model is configurable (Claude or Gemini) per agent or per tier;
* cheap extraction work routes to a small model, reasoning to a large one;
* token usage and estimated cost are captured in one ledger per run;
* with no API key present, calls go to a deterministic ``mock`` provider so
  CI and the evals run offline (see ``register_mock``).

Configuration (env vars, all optional):

    SIGHTLINE_PROVIDER          anthropic | gemini | mock   (default: auto)
    SIGHTLINE_MODEL_SMALL       model for tier "small"  (extraction, mapping)
    SIGHTLINE_MODEL_LARGE       model for tier "large"  (reasoning, judgment)
    SIGHTLINE_MODEL_<AGENT>     per-agent override, e.g. SIGHTLINE_MODEL_MAPPER=gemini:gemini-2.5-flash
                                ("provider:model" or bare model for the default provider)

"auto" picks anthropic if ANTHROPIC_API_KEY is set, else gemini if
GEMINI_API_KEY / GOOGLE_API_KEY is set, else mock.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()

Tier = Literal["small", "large"]

# Agent name -> tier. Extraction/mapping are cheap; reasoning/judgment is not.
AGENT_TIERS: dict[str, Tier] = {
    "mapper": "small",          # propose column mappings
    "contract_extractor": "small",
    "cre_extractor": "small",
    "extractor": "small",
    "investor_qa": "small",
    "explainer": "large",       # explain findings + draft dispute notes
    "judgment": "large",        # surface judgment_required items
    "risk": "large",
    "summarizer": "large",
}

DEFAULT_MODELS: dict[str, dict[Tier, str]] = {
    "anthropic": {"small": "claude-haiku-5-5", "large": "claude-opus-5-5"},
    # Gemini model ids change often; override with SIGHTLINE_MODEL_SMALL/LARGE.
    "gemini": {"small": "gemini-2.5-flash", "large": "gemini-2.5-pro"},
    "mock": {"small": "mock-small", "large": "mock-large"},
}

# USD per 1M tokens (input, output). Claude prices: Anthropic list prices as of
# 2026-11. Gemini prices are deliberately not hard-coded: set
# SIGHTLINE_PRICE_<MODEL_ID_UPPER_UNDERSCORED>="in,out" to get a cost figure.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "mock-small": (0.0, 0.0),
    "mock-large": (0.0, 0.0),
}


class MissingAPIKeyError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------
def detect_provider() -> str:
    explicit = os.environ.get("SIGHTLINE_PROVIDER", "auto").lower()
    if explicit != "auto":
        return explicit
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "mock"


def resolve_model(agent: str) -> tuple[str, str]:
    """Return (provider, model) for an agent."""
    override = os.environ.get(f"SIGHTLINE_MODEL_{agent.upper()}")
    provider = detect_provider()
    if override:
        if ":" in override:
            p, m = override.split(":", 1)
            return p.lower(), m
        return provider, override
    tier = AGENT_TIERS.get(agent, "large")
    env_tier = os.environ.get(f"SIGHTLINE_MODEL_{tier.upper()}")
    if env_tier:
        if ":" in env_tier:
            p, m = env_tier.split(":", 1)
            return p.lower(), m
        return provider, env_tier
    return provider, DEFAULT_MODELS.get(provider, DEFAULT_MODELS["mock"])[tier]


def price_for(model: str) -> tuple[float, float] | None:
    env = os.environ.get("SIGHTLINE_PRICE_" + model.upper().replace("-", "_").replace(".", "_"))
    if env:
        a, b = env.split(",")
        return float(a), float(b)
    return PRICES_PER_MTOK.get(model)


# ---------------------------------------------------------------------------
# Cost ledger
# ---------------------------------------------------------------------------
@dataclass
class CallRecord:
    agent: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float | None


@dataclass
class Ledger:
    calls: list[CallRecord] = field(default_factory=list)

    def add(self, rec: CallRecord) -> None:
        self.calls.append(rec)

    @property
    def total_cost(self) -> float | None:
        if any(c.cost_usd is None for c in self.calls):
            return None
        return round(sum(c.cost_usd or 0.0 for c in self.calls), 6)

    def summary_rows(self) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for c in self.calls:
            r = rows.setdefault(
                (c.agent, c.model),
                {"agent": c.agent, "provider": c.provider, "model": c.model,
                 "calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
            )
            r["calls"] += 1
            r["tokens_in"] += c.tokens_in
            r["tokens_out"] += c.tokens_out
            if r["cost_usd"] is not None:
                r["cost_usd"] = None if c.cost_usd is None else r["cost_usd"] + c.cost_usd
        return list(rows.values())

    def render(self) -> str:
        lines = [f"{'agent':<20}{'model':<22}{'calls':>6}{'tok_in':>10}{'tok_out':>9}{'cost $':>11}"]
        for r in self.summary_rows():
            cost = "n/a" if r["cost_usd"] is None else f"{r['cost_usd']:.4f}"
            lines.append(f"{r['agent']:<20}{r['model']:<22}{r['calls']:>6}{r['tokens_in']:>10}"
                         f"{r['tokens_out']:>9}{cost:>11}")
        total = self.total_cost
        lines.append(f"{'TOTAL':<48}{sum(c.tokens_in for c in self.calls):>10}"
                     f"{sum(c.tokens_out for c in self.calls):>9}"
                     f"{('n/a' if total is None else f'{total:.4f}'):>11}")
        return "\n".join(lines)


_local = threading.local()


def ledger() -> Ledger:
    if not hasattr(_local, "ledger"):
        _local.ledger = Ledger()
    return _local.ledger


def reset_ledger() -> Ledger:
    _local.ledger = Ledger()
    return _local.ledger


def _record(agent: str, provider: str, model: str, tin: int, tout: int) -> None:
    price = price_for(model)
    cost = None if price is None else (tin * price[0] + tout * price[1]) / 1_000_000
    ledger().add(CallRecord(agent, provider, model, tin, tout, cost))


# ---------------------------------------------------------------------------
# Mock provider: deterministic handlers registered per tool name
# ---------------------------------------------------------------------------
MockHandler = Callable[[str, str], dict[str, Any]]  # (system, user_content) -> data
_MOCKS: dict[str, MockHandler] = {}


def register_mock(tool_name: str, handler: MockHandler) -> None:
    """Register an offline stand-in for a structured call. Handlers must be
    deterministic and must not invent numbers (they read from the input or
    from a recorded, citation-verified fixture)."""
    _MOCKS[tool_name] = handler


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Schema helpers
# ---------------------------------------------------------------------------
def _coerce_to_schema(value: Any, schema: dict[str, Any]) -> Any:
    """Models occasionally double-encode a nested array/object as a JSON
    string. Walk the schema and repair those fields."""
    if not isinstance(schema, dict):
        return value
    schema_type = schema.get("type")
    if schema_type in ("object", "array") and isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if schema_type == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _coerce_to_schema(v, props.get(k, {})) for k, v in value.items()}
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items", {})
        return [_coerce_to_schema(v, item_schema) for v in value]
    return value


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a schema acceptable to strict structured outputs: every object
    gets additionalProperties=false and all properties required."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if out.get("type") == "object" or "properties" in out:
        props = {k: strict_schema(v) for k, v in out.get("properties", {}).items()}
        out["properties"] = props
        out["required"] = list(props)
        out["additionalProperties"] = False
    if "items" in out:
        out["items"] = strict_schema(out["items"])
    return out


@dataclass
class StructuredResult:
    data: dict[str, Any]
    tokens_in: int
    tokens_out: int
    provider: str = "mock"
    model: str = "mock"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def call_structured(
    system: str,
    user_content: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict[str, Any],
    agent: str = "extractor",
    max_tokens: int = 16000,
    model: str | None = None,
) -> StructuredResult:
    """Ask the routed model for JSON matching ``input_schema``."""
    provider, routed_model = resolve_model(agent)
    model = model or routed_model

    if provider == "mock":
        handler = _MOCKS.get(tool_name)
        if handler is None:
            raise MissingAPIKeyError(
                f"No API key set and no offline mock registered for '{tool_name}'. "
                "Set ANTHROPIC_API_KEY or GEMINI_API_KEY (see .env.example)."
            )
        data = handler(system, user_content)
        tin, tout = _estimate_tokens(system + user_content), _estimate_tokens(json.dumps(data))
        _record(agent, "mock", model, tin, tout)
        return StructuredResult(data, tin, tout, "mock", model)

    instruction = (
        f"{system}\n\nRespond only with a JSON object for '{tool_name}': {tool_description}"
    )
    if provider == "anthropic":
        data, tin, tout = _anthropic_json(instruction, user_content, input_schema, model, max_tokens)
    elif provider == "gemini":
        data, tin, tout = _gemini_json(instruction, user_content, input_schema, model)
    else:
        raise ValueError(f"Unknown provider: {provider}")
    data = _coerce_to_schema(data, input_schema)
    _record(agent, provider, model, tin, tout)
    return StructuredResult(data, tin, tout, provider, model)


def call_text(
    system: str,
    user_content: str,
    agent: str = "summarizer",
    max_tokens: int = 16000,
    model: str | None = None,
) -> tuple[str, int, int]:
    provider, routed_model = resolve_model(agent)
    model = model or routed_model
    if provider == "mock":
        raise MissingAPIKeyError(
            "Free-text generation needs a real model. Set ANTHROPIC_API_KEY or GEMINI_API_KEY."
        )
    if provider == "anthropic":
        client = _anthropic_client()
        resp = client.messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user_content}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
    else:
        client = _gemini_client()
        from google.genai import types

        resp = client.models.generate_content(
            model=model, contents=user_content,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        text = resp.text or ""
        tin = resp.usage_metadata.prompt_token_count or 0
        tout = resp.usage_metadata.candidates_token_count or 0
    _record(agent, provider, model, tin, tout)
    return text, tin, tout


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------
def _anthropic_client():
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise MissingAPIKeyError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env.")
    return anthropic.Anthropic()


def _anthropic_json(system, user_content, schema, model, max_tokens):
    client = _anthropic_client()
    # Structured outputs (output_config.format) rather than forced tool_choice,
    # which current Claude models reject.
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_config={"format": {"type": "json_schema", "schema": strict_schema(schema)}},
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("Model declined the request (stop_reason=refusal)")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text), resp.usage.input_tokens, resp.usage.output_tokens


def _gemini_client():
    from google import genai

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise MissingAPIKeyError("GEMINI_API_KEY is not set. Copy .env.example to .env.")
    return genai.Client(api_key=key)


def _gemini_json(system, user_content, schema, model):
    from google.genai import types

    client = _gemini_client()
    resp = client.models.generate_content(
        model=model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
        ),
    )
    usage = resp.usage_metadata
    return (json.loads(resp.text), usage.prompt_token_count or 0, usage.candidates_token_count or 0)
