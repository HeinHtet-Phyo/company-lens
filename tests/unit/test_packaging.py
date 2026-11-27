"""pyproject must ship the static UI and prompt files (a bare `pip install .` dropped them)."""

from __future__ import annotations

import tomllib
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "src" / "companylens"


def test_package_data_covers_static_ui_and_prompts() -> None:
    cfg = tomllib.loads((PKG.parents[1] / "pyproject.toml").read_text())
    patterns = cfg["tool"]["setuptools"]["package-data"]["companylens"]
    shipped = {str(p.relative_to(PKG)) for pat in patterns for p in PKG.glob(pat)}
    assert "api/static/index.html" in shipped
    assert "agent/prompts/v1/system.txt" in shipped
    assert "agent/prompts/v1/report.txt" in shipped
