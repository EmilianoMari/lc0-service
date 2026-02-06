"""Configuration for Chess Engine Service."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # LC0 Engine
    lc0_path: Path = Path(os.getenv("LC0_PATH", "/opt/lc0/lc0"))
    lc0_network: Path = Path(os.getenv("LC0_NETWORK", "/app/networks/BT4.pb.gz"))
    lc0_backend: str = "cuda-fp16"
    lc0_gpu_ids: str = "0"  # Comma-separated
    lc0_hash_mb: int = 2048
    lc0_threads: int = 2

    # Maia (uses LC0 engine with different weights)
    maia_network: Path = Path(os.getenv("MAIA_NETWORK", "/app/networks/maia-1900.pb.gz"))
    maia_enabled: bool = True

    # Stockfish Engine
    stockfish_path: Path = Path(os.getenv("STOCKFISH_PATH", "/opt/stockfish/stockfish"))
    stockfish_hash_mb: int = 2048
    stockfish_threads: int = 4
    stockfish_enabled: bool = True

    # Default analysis parameters
    default_nodes: int = 100000
    default_num_moves: int = 10
    default_depth: int = 20  # For Stockfish

    class Config:
        env_prefix = ""
        case_sensitive = False

    @property
    def gpu_ids_list(self) -> list[int]:
        """Parse GPU IDs from comma-separated string."""
        return [int(x.strip()) for x in self.lc0_gpu_ids.split(",")]


settings = Settings()
