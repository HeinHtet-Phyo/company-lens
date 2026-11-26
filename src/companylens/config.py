"""Application settings and named agent configurations."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # API keys
    companies_house_api_key: str = Field(default="")
    fca_api_email: str = Field(default="")
    fca_api_key: str = Field(default="")
    nebius_api_key: str = Field(default="")
    mistral_api_key: str = Field(default="")

    # Observability
    langfuse_public_key: str = Field(default="")
    langfuse_secret_key: str = Field(default="")
    langfuse_host: str = Field(default="https://cloud.langfuse.com")

    # Budget / rate limits
    daily_budget_gbp: float = Field(default=0.50)

    # LLM endpoints
    nebius_base_url: str = Field(default="https://api.tokenfactory.nebius.com/v1")
    mistral_base_url: str = Field(default="https://api.mistral.ai/v1")

    # Agent guards (defaults; overridden per config)
    max_tool_calls: int = Field(default=12)
    max_llm_rounds: int = Field(default=8)
    max_wall_seconds: int = Field(default=60)
    max_cost_gbp: float = Field(default=0.02)


class AgentConfig:
    """Named configuration for one agent variant."""

    def __init__(
        self,
        name: str,
        llm_provider: str,  # "nebius" | "mistral"
        model: str,
        summary_model: str,
        judge_model: str,
        use_claim_check: bool = True,
        use_agent: bool = True,
        max_tool_calls: int = 12,
        max_llm_rounds: int = 8,
        max_wall_seconds: int = 60,
        max_cost_gbp: float = 0.02,
    ) -> None:
        self.name = name
        self.llm_provider = llm_provider
        self.model = model
        self.summary_model = summary_model
        self.judge_model = judge_model
        self.use_claim_check = use_claim_check
        self.use_agent = use_agent
        self.max_tool_calls = max_tool_calls
        self.max_llm_rounds = max_llm_rounds
        self.max_wall_seconds = max_wall_seconds
        self.max_cost_gbp = max_cost_gbp


AGENT_CONFIGS: dict[str, AgentConfig] = {
    "agent_qwen": AgentConfig(
        name="agent_qwen",
        llm_provider="nebius",
        model="Qwen/Qwen3.8-27B",
        summary_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        judge_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
    ),
    "agent_mistral": AgentConfig(
        name="agent_mistral",
        llm_provider="mistral",
        model="mistral-small-latest",
        summary_model="mistral-small-latest",
        judge_model="mistral-small-latest",
    ),
    "agent_small": AgentConfig(
        name="agent_small",
        llm_provider="nebius",
        model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        summary_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        judge_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
    ),
    "baseline_fixed": AgentConfig(
        name="baseline_fixed",
        llm_provider="nebius",
        model="Qwen/Qwen3.8-27B",
        summary_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        judge_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        use_agent=False,
    ),
    "agent_qwen_noclaimcheck": AgentConfig(
        name="agent_qwen_noclaimcheck",
        llm_provider="nebius",
        model="Qwen/Qwen3.8-27B",
        summary_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        judge_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        use_claim_check=False,
    ),
    "agent_qwen_tight": AgentConfig(
        name="agent_qwen_tight",
        llm_provider="nebius",
        model="Qwen/Qwen3.8-27B",
        summary_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        judge_model="Qwen/Qwen3-30B-A3B-Instruct-2507",
        max_tool_calls=3,
        max_llm_rounds=4,
    ),
}

DEFAULT_CONFIG = "agent_qwen"


def get_settings() -> Settings:
    return Settings()
