from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    frontend_dist: Path
    archive_dir: Path
    runtime_version: str = "0.3.0"
    host: str = "127.0.0.1"
    openai_api_key: str | None = field(default=None, repr=False)
    openai_model: str = "gpt-5.6-terra"
    openai_timeout_seconds: int = 30
    openai_max_retries: int = 1
    openai_max_in_flight: int = 4
    openai_max_output_tokens: int = 1_800
    holder_snapshot_path: Path | None = None
    holder_snapshot_chain_id: str = "ethereum"

    @classmethod
    def from_environment(cls) -> "Settings":
        workspace = Path(__file__).resolve().parents[2]
        data_dir = Path(os.getenv("SANDBOX_DATA_DIR", workspace / "data")).resolve()
        if os.getenv("SANDBOX_OPENAI_STORE", "false").casefold() not in {"false", "0", "no"}:
            raise ValueError("SANDBOX_OPENAI_STORE must remain false")
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "sandbox.db",
            frontend_dist=workspace / "frontend" / "dist",
            archive_dir=data_dir / "archives",
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            openai_model=os.getenv("SANDBOX_OPENAI_MODEL", "gpt-5.6-terra"),
            openai_timeout_seconds=int(os.getenv("SANDBOX_OPENAI_TIMEOUT_SECONDS", "30")),
            openai_max_retries=int(os.getenv("SANDBOX_OPENAI_MAX_RETRIES", "1")),
            openai_max_in_flight=int(os.getenv("SANDBOX_OPENAI_MAX_IN_FLIGHT", "4")),
            openai_max_output_tokens=int(os.getenv("SANDBOX_OPENAI_MAX_OUTPUT_TOKENS", "1800")),
            holder_snapshot_path=Path(os.environ["SANDBOX_HOLDER_SNAPSHOT_PATH"]).resolve() if os.getenv("SANDBOX_HOLDER_SNAPSHOT_PATH") else None,
            holder_snapshot_chain_id=os.getenv("SANDBOX_HOLDER_CHAIN_ID", "ethereum"),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
