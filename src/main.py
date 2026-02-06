"""Chess Engine Service - FastAPI entrypoint."""

import sys
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import router, register_engine
from .config import settings
from .engine import (
    EngineType,
    Lc0Config,
    Lc0Wrapper,
    StockfishConfig,
    StockfishWrapper,
)

# Configure logging
log_level = "DEBUG" if settings.debug else "INFO"
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.stdlib.logging.INFO if not settings.debug else structlog.stdlib.logging.DEBUG
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Global engine instances
_engines: dict[EngineType, Lc0Wrapper | StockfishWrapper] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - starts and stops all engines."""
    global _engines

    logger.info("Starting Chess Engine Service")

    # ========== LC0 ==========
    logger.info(
        "Initializing LC0",
        lc0_path=str(settings.lc0_path),
        network=str(settings.lc0_network),
        backend=settings.lc0_backend,
        gpu_ids=settings.gpu_ids_list,
    )

    lc0_config = Lc0Config(
        executable_path=settings.lc0_path,
        network_path=settings.lc0_network,
        backend=settings.lc0_backend,
        gpu_ids=settings.gpu_ids_list,
        hash_mb=settings.lc0_hash_mb,
        threads=settings.lc0_threads,
        multipv=settings.default_num_moves,
    )

    lc0_engine = Lc0Wrapper(lc0_config, engine_type=EngineType.LC0)
    try:
        await lc0_engine.start()
        _engines[EngineType.LC0] = lc0_engine
        register_engine(EngineType.LC0, lc0_engine)
        logger.info("LC0 engine started successfully")
    except Exception as e:
        logger.error("Failed to start LC0 engine", error=str(e))
        # LC0 is required, exit if it fails
        sys.exit(1)

    # ========== Maia (LC0 with Maia weights) ==========
    if settings.maia_enabled and settings.maia_network.exists():
        logger.info(
            "Initializing Maia",
            network=str(settings.maia_network),
        )

        maia_config = Lc0Config(
            executable_path=settings.lc0_path,
            network_path=settings.maia_network,
            backend=settings.lc0_backend,
            gpu_ids=settings.gpu_ids_list,
            hash_mb=settings.lc0_hash_mb // 2,  # Less hash for Maia
            threads=settings.lc0_threads,
            multipv=settings.default_num_moves,
        )

        maia_engine = Lc0Wrapper(maia_config, engine_type=EngineType.MAIA)
        try:
            await maia_engine.start()
            _engines[EngineType.MAIA] = maia_engine
            register_engine(EngineType.MAIA, maia_engine)
            logger.info("Maia engine started successfully")
        except Exception as e:
            logger.warning("Failed to start Maia engine", error=str(e))
    else:
        logger.info("Maia disabled or network not found")

    # ========== Stockfish ==========
    if settings.stockfish_enabled and settings.stockfish_path.exists():
        logger.info(
            "Initializing Stockfish",
            stockfish_path=str(settings.stockfish_path),
        )

        stockfish_config = StockfishConfig(
            executable_path=settings.stockfish_path,
            hash_mb=settings.stockfish_hash_mb,
            threads=settings.stockfish_threads,
            multipv=settings.default_num_moves,
        )

        stockfish_engine = StockfishWrapper(stockfish_config)
        try:
            await stockfish_engine.start()
            _engines[EngineType.STOCKFISH] = stockfish_engine
            register_engine(EngineType.STOCKFISH, stockfish_engine)
            logger.info("Stockfish engine started successfully")
        except Exception as e:
            logger.warning("Failed to start Stockfish engine", error=str(e))
    else:
        logger.info("Stockfish disabled or binary not found")

    logger.info(
        "Chess Engine Service ready",
        engines=list(_engines.keys()),
    )

    yield

    # Shutdown
    logger.info("Shutting down Chess Engine Service")
    for engine_type, engine in _engines.items():
        try:
            await engine.stop()
            logger.info(f"{engine_type.value} engine stopped")
        except Exception as e:
            logger.error(f"Error stopping {engine_type.value}", error=str(e))


# Create FastAPI app
app = FastAPI(
    title="Chess Engine Service",
    description="Multi-engine chess analysis service supporting LC0, Stockfish, and Maia",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
