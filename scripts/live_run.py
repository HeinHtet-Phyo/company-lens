"""Run the agent live on one query and print a compact result (never prints keys)."""

from __future__ import annotations

import asyncio
import sys

from companylens.agent.graph import CompanyAgent
from companylens.config import AGENT_CONFIGS, get_settings
from companylens.llm import LLMClient
from companylens.observability import Tracer
from companylens.tools.company_tools import build_registry


async def main(query: str, config_name: str) -> None:
    settings = get_settings()
    config = AGENT_CONFIGS[config_name]
    agent = CompanyAgent(
        build_registry(settings), LLMClient(config, settings), config, Tracer(settings)
    )
    resp = await agent.run(query)
    if resp.report is None:
        print(resp.type, resp.message, [o.company_name for o in resp.clarification_options or []])
        return
    r = resp.report
    print(r.company.name, r.company.number, r.company.status, "|", r.risk_level)
    for f in r.red_flags:
        print(" ", f.rule_id, f.severity, f.explanation)
    print("summary:", r.summary)
    print("limitations:", r.limitations)
    print("stats:", r.stats.model_dump())


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "agent_qwen"))
