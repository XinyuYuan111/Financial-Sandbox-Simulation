from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    database_path: Path
    frontend_dist: Path
    archive_dir: Path
    runtime_version: str = "0.2.0"
    host: str = "127.0.0.1"

    @classmethod
    def from_environment(cls) -> "Settings":
        workspace = Path(__file__).resolve().parents[2]
        data_dir = Path(os.getenv("SANDBOX_DATA_DIR", workspace / "data")).resolve()
        return cls(
            data_dir=data_dir,
            database_path=data_dir / "sandbox.db",
            frontend_dist=workspace / "frontend" / "dist",
            archive_dir=data_dir / "archives",
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

