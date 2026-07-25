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
    openai_base_url: str | None = None
    openai_model: str = "gpt-5.6-terra"
    openai_timeout_seconds: int = 30
    openai_max_retries: int = 1
    openai_max_in_flight: int = 4
    openai_max_output_tokens: int = 4_096
    deepseek_api_key: str | None = field(default=None, repr=False)
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: int = 60
    deepseek_max_retries: int = 1
    deepseek_max_in_flight: int = 4
    deepseek_max_output_tokens: int = 4_096
    holder_snapshot_path: Path | None = None
    holder_snapshot_chain_id: str = "ethereum"
    injective_rpc_url: str = "https://k8s.testnet.json-rpc.injective.network/"
    injective_token_address: str | None = None
    injective_holder_start_block: int = 0
    cors_allowed_origins: frozenset[str] = field(default_factory=frozenset)
    attestation_enabled: bool = False
    attestation_contract_address: str | None = None
    attestation_private_key: str | None = field(default=None, repr=False)

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
            openai_base_url=(os.getenv("SANDBOX_OPENAI_BASE_URL") or "").strip() or None,
            openai_model=os.getenv("SANDBOX_OPENAI_MODEL", "gpt-5.6-terra"),
            openai_timeout_seconds=int(os.getenv("SANDBOX_OPENAI_TIMEOUT_SECONDS", "30")),
            openai_max_retries=int(os.getenv("SANDBOX_OPENAI_MAX_RETRIES", "1")),
            openai_max_in_flight=int(os.getenv("SANDBOX_OPENAI_MAX_IN_FLIGHT", "4")),
            openai_max_output_tokens=int(os.getenv("SANDBOX_OPENAI_MAX_OUTPUT_TOKENS", "4096")),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or None,
            deepseek_base_url=(os.getenv("SANDBOX_DEEPSEEK_BASE_URL") or "https://api.deepseek.com").strip().rstrip("/"),
            deepseek_model=os.getenv("SANDBOX_DEEPSEEK_MODEL", "deepseek-chat"),
            deepseek_timeout_seconds=int(os.getenv("SANDBOX_DEEPSEEK_TIMEOUT_SECONDS", "60")),
            deepseek_max_retries=int(os.getenv("SANDBOX_DEEPSEEK_MAX_RETRIES", "1")),
            deepseek_max_in_flight=int(os.getenv("SANDBOX_DEEPSEEK_MAX_IN_FLIGHT", "4")),
            deepseek_max_output_tokens=int(os.getenv("SANDBOX_DEEPSEEK_MAX_OUTPUT_TOKENS", "4096")),
            holder_snapshot_path=Path(os.environ["SANDBOX_HOLDER_SNAPSHOT_PATH"]).resolve() if os.getenv("SANDBOX_HOLDER_SNAPSHOT_PATH") else None,
            holder_snapshot_chain_id=os.getenv("SANDBOX_HOLDER_CHAIN_ID", "ethereum"),
            injective_rpc_url=os.getenv("SANDBOX_INJECTIVE_RPC_URL", "https://k8s.testnet.json-rpc.injective.network/").strip().rstrip("/"),
            injective_token_address=(os.getenv("SANDBOX_INJECTIVE_TOKEN_ADDRESS") or "").strip() or None,
            injective_holder_start_block=int(os.getenv("SANDBOX_INJECTIVE_HOLDER_START_BLOCK", "0")),
            attestation_enabled=os.getenv("SANDBOX_ATTESTATION_ENABLED", "false").lower() in {"true", "1"},
            attestation_contract_address=(os.getenv("SANDBOX_ATTESTATION_CONTRACT") or "").strip() or None,
            attestation_private_key=(os.getenv("SANDBOX_ATTESTATION_KEY") or "").strip() or None,
            cors_allowed_origins=frozenset(
                o.strip().rstrip("/")
                for o in os.getenv("SANDBOX_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
                if o.strip()
            ),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
