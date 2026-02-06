"""API routes for Chess Engine Service."""

from fastapi import APIRouter, HTTPException

from ..engine import BaseEngine, EngineType
from .schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    EngineStatus,
    HealthResponse,
    MoveCandidateResponse,
    EngineType as SchemaEngineType,
)

router = APIRouter()

# Engine instances (set by main.py on startup)
_engines: dict[EngineType, BaseEngine] = {}


def register_engine(engine_type: EngineType, engine: BaseEngine) -> None:
    """Register an engine instance."""
    _engines[engine_type] = engine


def get_engine(engine_type: EngineType) -> BaseEngine:
    """Get an engine instance or raise if not available."""
    # Map schema enum to engine enum
    engine_enum = EngineType(engine_type.value)

    if engine_enum not in _engines:
        raise HTTPException(
            status_code=503,
            detail=f"Engine '{engine_type.value}' not available"
        )
    return _engines[engine_enum]


def get_available_engines() -> list[EngineType]:
    """Get list of available engines."""
    return list(_engines.keys())


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_position(request: AnalyzeRequest) -> AnalyzeResponse:
    """
    Analyze a chess position and return candidate moves with evaluations.

    Supports multiple engines:
    - **lc0**: Leela Chess Zero neural network (AlphaZero-style)
    - **stockfish**: Stockfish with NNUE (strongest traditional engine)
    - **maia**: Human-like engine (predicts human moves)
    """
    engine_type = EngineType(request.engine.value)
    engine = get_engine(request.engine)

    try:
        # Use appropriate parameters based on engine type
        if engine_type == EngineType.STOCKFISH:
            # Stockfish prefers depth
            analysis = await engine.analyze_position(
                fen=request.fen,
                depth=request.depth or 20,
                num_moves=request.num_moves,
            )
        else:
            # LC0/Maia use nodes
            analysis = await engine.analyze_position(
                fen=request.fen,
                nodes=request.nodes,
                num_moves=request.num_moves,
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    candidates = [
        MoveCandidateResponse(
            move=c.move,
            move_san=c.move_san,
            score_cp=c.score_cp,
            score_wdl=list(c.score_wdl),
            rank=c.rank,
        )
        for c in analysis.candidates
    ]

    return AnalyzeResponse(
        fen=analysis.fen,
        engine=engine_type.value,
        candidates=candidates,
        evaluation_cp=analysis.evaluation_cp,
        total_nodes=analysis.total_nodes,
        time_ms=analysis.time_ms,
        depth=analysis.depth,
    )


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Check service health and engine status."""
    from ..config import settings

    engine_statuses = []

    # Check LC0
    lc0_ready = False
    if EngineType.LC0 in _engines:
        try:
            lc0_ready = await _engines[EngineType.LC0].is_ready()
        except Exception:
            pass
    engine_statuses.append(EngineStatus(
        name="lc0",
        ready=lc0_ready,
        enabled=True,  # LC0 always enabled
    ))

    # Check Stockfish
    stockfish_ready = False
    if EngineType.STOCKFISH in _engines:
        try:
            stockfish_ready = await _engines[EngineType.STOCKFISH].is_ready()
        except Exception:
            pass
    engine_statuses.append(EngineStatus(
        name="stockfish",
        ready=stockfish_ready,
        enabled=settings.stockfish_enabled,
    ))

    # Check Maia
    maia_ready = False
    if EngineType.MAIA in _engines:
        try:
            maia_ready = await _engines[EngineType.MAIA].is_ready()
        except Exception:
            pass
    engine_statuses.append(EngineStatus(
        name="maia",
        ready=maia_ready,
        enabled=settings.maia_enabled,
    ))

    # Overall status
    any_ready = any(e.ready for e in engine_statuses)
    status = "healthy" if any_ready else "degraded"

    return HealthResponse(
        status=status,
        engines=engine_statuses,
    )


@router.get("/engines")
async def list_engines() -> dict:
    """List available chess engines."""
    from ..config import settings

    return {
        "engines": [
            {
                "id": "lc0",
                "name": "Leela Chess Zero",
                "description": "Neural network engine (AlphaZero-style)",
                "type": "neural_network",
                "available": EngineType.LC0 in _engines,
            },
            {
                "id": "stockfish",
                "name": "Stockfish",
                "description": "Strongest traditional engine with NNUE",
                "type": "traditional",
                "available": EngineType.STOCKFISH in _engines and settings.stockfish_enabled,
            },
            {
                "id": "maia",
                "name": "Maia Chess",
                "description": "Human-like engine (predicts human moves)",
                "type": "neural_network",
                "available": EngineType.MAIA in _engines and settings.maia_enabled,
            },
        ]
    }
