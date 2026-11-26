"""Thin LLM wrapper around AsyncOpenAI with token + cost tracking."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from companylens.config import AgentConfig, Settings

# ---------------------------------------------------------------------------
# Pricing table: (input_per_1m_gbp, output_per_1m_gbp)
# USD prices multiplied by 0.80 for GBP
# ---------------------------------------------------------------------------
PRICING_GBP: dict[str, tuple[float, float]] = {
    "Qwen3-235B": (0.20 * 0.80, 0.60 * 0.80),
    "Qwen3-30B": (0.10 * 0.80, 0.30 * 0.80),
    "Qwen3-14B": (0.07 * 0.80, 0.21 * 0.80),
    "mistral-small": (0.10 * 0.80, 0.30 * 0.80),
}

_DEFAULT_PRICING_GBP: tuple[float, float] = (0.50 * 0.80, 1.50 * 0.80)


def _lookup_pricing(model: str) -> tuple[float, float]:
    """Find the pricing tuple for a model by substring match."""
    for key, pricing in PRICING_GBP.items():
        if key in model:
            return pricing
    return _DEFAULT_PRICING_GBP


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated cost in GBP."""
    in_price, out_price = _lookup_pricing(model)
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


class LLMClient:
    """Thin wrapper: retries, timeouts, token + cost tracking."""

    def __init__(self, config: AgentConfig, settings: Settings) -> None:
        if config.llm_provider == "mistral":
            base_url = settings.mistral_base_url
            api_key = settings.mistral_api_key
        else:
            base_url = settings.nebius_base_url
            api_key = settings.nebius_api_key

        self._model = config.model
        self._summary_model = config.summary_model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=30.0,
            max_retries=2,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        response_format: dict[str, Any] | None = None,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> tuple[Any, int, int, float]:
        """Call the LLM.

        Returns:
            Tuple of (response_message, input_tokens, output_tokens, cost_gbp).
        """
        used_model = model or self._model
        kwargs: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = await self._client.chat.completions.create(**kwargs)
        input_tokens: int = response.usage.prompt_tokens if response.usage else 0
        output_tokens: int = response.usage.completion_tokens if response.usage else 0
        cost_gbp = _calc_cost(used_model, input_tokens, output_tokens)
        return response.choices[0].message, input_tokens, output_tokens, cost_gbp

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> tuple[dict[str, Any], int, int, float]:
        """Call with JSON output mode. Parse and return the JSON."""
        message, input_tokens, output_tokens, cost_gbp = await self.chat(
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            model=model,
        )
        content: str = message.content or "{}"
        parsed: dict[str, Any] = json.loads(content)
        return parsed, input_tokens, output_tokens, cost_gbp
