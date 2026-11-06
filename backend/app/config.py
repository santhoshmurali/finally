"""Runtime settings read from environment variables."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = "../db/finally.db"
DEFAULT_STATIC_DIR = "../static"


@dataclass(frozen=True, slots=True)
class Settings:
    """Paths and LLM options. Relative paths resolve against the working directory."""

    db_path: Path
    static_dir: Path
    llm_mock: bool
    openrouter_api_key: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        return cls(
            db_path=Path(env.get("FINALLY_DB_PATH", DEFAULT_DB_PATH)),
            static_dir=Path(env.get("FINALLY_STATIC_DIR", DEFAULT_STATIC_DIR)),
            llm_mock=env.get("LLM_MOCK", "false").strip().lower() == "true",
            openrouter_api_key=env.get("OPENROUTER_API_KEY", "").strip(),
        )
