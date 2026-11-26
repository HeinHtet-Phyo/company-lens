"""Unit tests for the LLM client wrapper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from companylens.config import AgentConfig, Settings
from companylens.llm import PRICING_GBP, LLMClient, _calc_cost, _lookup_pricing

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_config(provider: str = "nebius", model: str = "Qwen/Qwen3-235B-A22B-fast") -> AgentConfig:
    return AgentConfig(
        name="test",
        llm_provider=provider,
        model=model,
        summary_model=model,
        judge_model=model,
    )


def make_settings() -> Settings:
    return Settings(
        nebius_api_key="test-nebius-key",
        mistral_api_key="test-mistral-key",
        nebius_base_url="https://api.nebius.test/v1",
        mistral_base_url="https://api.mistral.test/v1",
    )


def _make_mock_response(
    content: str, input_tokens: int = 100, output_tokens: int = 50
) -> MagicMock:
    """Build a mock OpenAI chat completion response."""
    usage = MagicMock()
    usage.prompt_tokens = input_tokens
    usage.completion_tokens = output_tokens

    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.usage = usage
    response.choices = [choice]
    return response


# ---------------------------------------------------------------------------
# Pricing tests
# ---------------------------------------------------------------------------


def test_pricing_gbp_has_known_models() -> None:
    assert "Qwen3-235B" in PRICING_GBP
    assert "Qwen3-30B" in PRICING_GBP
    assert "Qwen3-14B" in PRICING_GBP
    assert "mistral-small" in PRICING_GBP


def test_lookup_pricing_qwen_235b() -> None:
    in_price, out_price = _lookup_pricing("Qwen/Qwen3-235B-A22B-fast")
    expected_in = 0.20 * 0.80
    expected_out = 0.60 * 0.80
    assert abs(in_price - expected_in) < 1e-9
    assert abs(out_price - expected_out) < 1e-9


def test_lookup_pricing_mistral_small() -> None:
    in_price, out_price = _lookup_pricing("mistral-small-latest")
    expected_in = 0.10 * 0.80
    expected_out = 0.30 * 0.80
    assert abs(in_price - expected_in) < 1e-9
    assert abs(out_price - expected_out) < 1e-9


def test_lookup_pricing_unknown_model_uses_default() -> None:
    in_price, out_price = _lookup_pricing("some-unknown-model-xyz")
    expected_in = 0.50 * 0.80
    expected_out = 1.50 * 0.80
    assert abs(in_price - expected_in) < 1e-9
    assert abs(out_price - expected_out) < 1e-9


def test_calc_cost_qwen_235b() -> None:
    # 1M input + 1M output tokens of Qwen3-235B
    cost = _calc_cost("Qwen/Qwen3-235B-A22B-fast", 1_000_000, 1_000_000)
    expected = (0.20 + 0.60) * 0.80  # 0.64 GBP
    assert abs(cost - expected) < 1e-6


def test_calc_cost_zero_tokens() -> None:
    cost = _calc_cost("Qwen/Qwen3-14B-fast", 0, 0)
    assert cost == 0.0


# ---------------------------------------------------------------------------
# LLMClient.chat() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_returns_correct_tuple_shape() -> None:
    config = make_config()
    settings = make_settings()

    mock_response = _make_mock_response("Hello!", input_tokens=10, output_tokens=5)

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        llm = LLMClient(config, settings)
        message, in_tok, out_tok, cost = await llm.chat(
            messages=[{"role": "user", "content": "Hi"}]
        )

    assert message.content == "Hello!"
    assert in_tok == 10
    assert out_tok == 5
    assert isinstance(cost, float)
    assert cost >= 0.0


@pytest.mark.asyncio
async def test_chat_cost_calculation_correct() -> None:
    """Cost for Qwen3-235B with 1000 in + 500 out tokens should match formula."""
    config = make_config(model="Qwen/Qwen3-235B-A22B-fast")
    settings = make_settings()

    mock_response = _make_mock_response("OK", input_tokens=1000, output_tokens=500)

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        llm = LLMClient(config, settings)
        _, _in_tok, _out_tok, cost = await llm.chat(messages=[{"role": "user", "content": "test"}])

    expected_cost = _calc_cost("Qwen/Qwen3-235B-A22B-fast", 1000, 500)
    assert abs(cost - expected_cost) < 1e-9


@pytest.mark.asyncio
async def test_chat_passes_tools_when_provided() -> None:
    config = make_config()
    settings = make_settings()
    mock_response = _make_mock_response("tool call result")

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        llm = LLMClient(config, settings)
        tools = [{"type": "function", "function": {"name": "my_tool", "description": "test"}}]
        await llm.chat(messages=[{"role": "user", "content": "use tool"}], tools=tools)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "tools" in call_kwargs
        assert call_kwargs["tools"] == tools


# ---------------------------------------------------------------------------
# LLMClient.chat_json() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_json_parses_response_correctly() -> None:
    config = make_config()
    settings = make_settings()

    payload = {"risk_level": "High", "summary": "Test summary [e1]."}
    mock_response = _make_mock_response(json.dumps(payload), input_tokens=20, output_tokens=30)

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        llm = LLMClient(config, settings)
        result, in_tok, out_tok, cost = await llm.chat_json(
            messages=[{"role": "user", "content": "give me json"}]
        )

    assert isinstance(result, dict)
    assert result["risk_level"] == "High"
    assert result["summary"] == "Test summary [e1]."
    assert in_tok == 20
    assert out_tok == 30
    assert isinstance(cost, float)


@pytest.mark.asyncio
async def test_chat_json_sets_response_format() -> None:
    config = make_config()
    settings = make_settings()
    mock_response = _make_mock_response('{"key": "value"}')

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_client

        llm = LLMClient(config, settings)
        await llm.chat_json(messages=[{"role": "user", "content": "json please"}])

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs.get("response_format") == {"type": "json_object"}


@pytest.mark.asyncio
async def test_chat_uses_mistral_base_url_for_mistral_provider() -> None:
    config = make_config(provider="mistral", model="mistral-small-latest")
    settings = make_settings()

    with patch("companylens.llm.AsyncOpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        LLMClient(config, settings)

        init_kwargs = mock_openai_cls.call_args[1]
        assert init_kwargs["base_url"] == settings.mistral_base_url
        assert init_kwargs["api_key"] == settings.mistral_api_key
