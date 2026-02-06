"""Base interface for chess engines."""

from abc import ABC, abstractmethod
from enum import Enum

from .move_candidates import PositionAnalysis


class EngineType(str, Enum):
    """Supported chess engines."""

    LC0 = "lc0"           # Leela Chess Zero - Neural network
    STOCKFISH = "stockfish"  # Stockfish - NNUE hybrid
    MAIA = "maia"         # Maia - Human-like (LC0 with Maia weights)


class BaseEngine(ABC):
    """Abstract base class for chess engines."""

    engine_type: EngineType

    @abstractmethod
    async def start(self) -> None:
        """Start the engine process."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the engine process."""
        pass

    @abstractmethod
    async def analyze_position(
        self,
        fen: str,
        nodes: int | None = None,
        depth: int | None = None,
        time_ms: int | None = None,
        num_moves: int | None = None,
    ) -> PositionAnalysis:
        """
        Analyze a chess position.

        Args:
            fen: Position in FEN notation
            nodes: Number of nodes to search (if supported)
            depth: Search depth
            time_ms: Time limit in milliseconds
            num_moves: Number of candidate moves to return

        Returns:
            PositionAnalysis with candidates and evaluation
        """
        pass

    @abstractmethod
    async def is_ready(self) -> bool:
        """Check if engine is ready for commands."""
        pass

    @abstractmethod
    async def new_game(self) -> None:
        """Signal start of a new game."""
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Check if engine process is running."""
        pass

    @property
    def name(self) -> str:
        """Human-readable engine name."""
        return self.engine_type.value
