"""Engine module - supports LC0, Stockfish, and Maia."""

from .base import BaseEngine, EngineType
from .move_candidates import MoveCandidate, PositionAnalysis
from .lc0_wrapper import Lc0Config, Lc0Wrapper, create_engine
from .stockfish_wrapper import StockfishConfig, StockfishWrapper, create_stockfish

__all__ = [
    # Base
    "BaseEngine",
    "EngineType",
    # Data classes
    "MoveCandidate",
    "PositionAnalysis",
    # LC0 / Maia
    "Lc0Config",
    "Lc0Wrapper",
    "create_engine",
    # Stockfish
    "StockfishConfig",
    "StockfishWrapper",
    "create_stockfish",
]
