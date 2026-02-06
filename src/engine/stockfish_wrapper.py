"""Wrapper per Stockfish via protocollo UCI."""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

import chess
import structlog

from .base import BaseEngine, EngineType
from .move_candidates import MoveCandidate, PositionAnalysis

logger = structlog.get_logger(__name__)


@dataclass
class StockfishConfig:
    """Configurazione per Stockfish engine."""

    executable_path: Path
    hash_mb: int = 2048
    threads: int = 4
    multipv: int = 10

    # NNUE
    use_nnue: bool = True

    # Skill level (0-20, 20 = strongest)
    skill_level: int = 20

    def to_uci_options(self) -> list[tuple[str, str]]:
        """Converte config in opzioni UCI."""
        options = [
            ("Hash", str(self.hash_mb)),
            ("Threads", str(self.threads)),
            ("MultiPV", str(self.multipv)),
            ("UCI_AnalyseMode", "true"),
        ]

        if self.use_nnue:
            options.append(("Use NNUE", "true"))

        if self.skill_level < 20:
            options.append(("Skill Level", str(self.skill_level)))

        return options


class StockfishWrapper(BaseEngine):
    """Wrapper asincrono per comunicazione con Stockfish via UCI."""

    engine_type = EngineType.STOCKFISH

    def __init__(self, config: StockfishConfig):
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._is_ready = False

    async def start(self) -> None:
        """Avvia il processo Stockfish."""
        if self._process is not None:
            logger.warning("Stockfish già avviato, riavvio...")
            await self.stop()

        logger.info("Avvio Stockfish", path=str(self.config.executable_path))

        self._process = await asyncio.create_subprocess_exec(
            str(self.config.executable_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Inizializzazione UCI
        await self._send_command("uci")
        await self._wait_for("uciok")

        # Configura opzioni
        for name, value in self.config.to_uci_options():
            await self._send_command(f"setoption name {name} value {value}")

        # Prepara engine
        await self._send_command("isready")
        await self._wait_for("readyok")

        self._is_ready = True
        logger.info("Stockfish pronto", threads=self.config.threads, hash=self.config.hash_mb)

    async def stop(self) -> None:
        """Ferma il processo Stockfish."""
        if self._process is None:
            return

        logger.info("Arresto Stockfish")
        await self._send_command("quit")

        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout arresto Stockfish, terminazione forzata")
            self._process.kill()
            await self._process.wait()

        self._process = None
        self._reader = None
        self._writer = None
        self._is_ready = False

    async def _send_command(self, command: str) -> None:
        """Invia comando UCI a Stockfish."""
        if self._writer is None:
            raise RuntimeError("Stockfish non avviato")

        logger.debug("UCI >>", command=command)
        self._writer.write(f"{command}\n".encode())
        await self._writer.drain()

    async def _read_line(self) -> str:
        """Legge una linea da Stockfish."""
        if self._reader is None:
            raise RuntimeError("Stockfish non avviato")

        line = await self._reader.readline()
        decoded = line.decode().strip()
        if decoded:
            logger.debug("UCI <<", response=decoded)
        return decoded

    async def _wait_for(self, expected: str) -> list[str]:
        """Legge linee fino a trovare quella attesa."""
        lines = []
        while True:
            line = await self._read_line()
            lines.append(line)
            if line.startswith(expected):
                return lines

    async def _read_until_bestmove(self) -> tuple[list[str], str]:
        """Legge output fino a bestmove, ritorna tutte le linee info."""
        info_lines = []
        while True:
            line = await self._read_line()
            if line.startswith("info") and "pv" in line:
                info_lines.append(line)
            elif line.startswith("bestmove"):
                return info_lines, line

    async def analyze_position(
        self,
        fen: str,
        nodes: int | None = None,
        depth: int | None = None,
        time_ms: int | None = None,
        num_moves: int | None = None,
    ) -> PositionAnalysis:
        """Analizza una posizione e ritorna le mosse candidate."""
        async with self._lock:
            if not self._is_ready:
                raise RuntimeError("Stockfish non pronto, chiamare start() prima")

            # Imposta MultiPV se richiesto
            if num_moves is not None and num_moves != self.config.multipv:
                await self._send_command(f"setoption name MultiPV value {num_moves}")

            # Imposta posizione
            await self._send_command(f"position fen {fen}")

            # Costruisci comando go
            # Stockfish usa depth o time, nodes è meno affidabile
            go_cmd = "go"
            if depth is not None:
                go_cmd += f" depth {depth}"
            elif time_ms is not None:
                go_cmd += f" movetime {time_ms}"
            elif nodes is not None:
                # Converti nodes in depth approssimativo per Stockfish
                # Rule of thumb: ~100k nodes per depth level
                approx_depth = max(15, min(30, 10 + nodes // 100000))
                go_cmd += f" depth {approx_depth}"
            else:
                go_cmd += " depth 20"

            await self._send_command(go_cmd)

            # Leggi risultati
            info_lines, bestmove_line = await self._read_until_bestmove()

            # Ripristina MultiPV se modificato
            if num_moves is not None and num_moves != self.config.multipv:
                await self._send_command(
                    f"setoption name MultiPV value {self.config.multipv}"
                )

            # Parse risultati
            return self._parse_analysis(fen, info_lines, bestmove_line)

    def _parse_analysis(
        self, fen: str, info_lines: list[str], bestmove_line: str
    ) -> PositionAnalysis:
        """Parsa l'output UCI in strutture dati."""
        board = chess.Board(fen)
        candidates: dict[int, MoveCandidate] = {}

        total_nodes = 0
        time_ms = 0
        nps = 0
        max_depth = 0
        max_seldepth = 0

        # Regex per parsing info lines
        multipv_pattern = re.compile(r"multipv (\d+)")
        depth_pattern = re.compile(r" depth (\d+)")
        seldepth_pattern = re.compile(r"seldepth (\d+)")
        nodes_pattern = re.compile(r"nodes (\d+)")
        time_pattern = re.compile(r" time (\d+)")
        nps_pattern = re.compile(r"nps (\d+)")
        score_cp_pattern = re.compile(r"score cp (-?\d+)")
        score_mate_pattern = re.compile(r"score mate (-?\d+)")
        pv_pattern = re.compile(r" pv (.+)$")

        for line in info_lines:
            if "multipv" not in line:
                continue

            # Estrai multipv index
            mpv_match = multipv_pattern.search(line)
            if not mpv_match:
                continue
            mpv_idx = int(mpv_match.group(1))

            # Estrai profondità
            depth_match = depth_pattern.search(line)
            depth = int(depth_match.group(1)) if depth_match else 0

            seldepth_match = seldepth_pattern.search(line)
            seldepth = int(seldepth_match.group(1)) if seldepth_match else 0

            # Estrai nodi/tempo
            nodes_match = nodes_pattern.search(line)
            nodes = int(nodes_match.group(1)) if nodes_match else 0

            time_match = time_pattern.search(line)
            if time_match:
                time_ms = max(time_ms, int(time_match.group(1)))

            nps_match = nps_pattern.search(line)
            if nps_match:
                nps = max(nps, int(nps_match.group(1)))

            total_nodes = max(total_nodes, nodes)
            max_depth = max(max_depth, depth)
            max_seldepth = max(max_seldepth, seldepth)

            # Estrai score
            score_cp = 0
            cp_match = score_cp_pattern.search(line)
            mate_match = score_mate_pattern.search(line)

            if mate_match:
                mate_in = int(mate_match.group(1))
                score_cp = 10000 - abs(mate_in) if mate_in > 0 else -10000 + abs(mate_in)
            elif cp_match:
                score_cp = int(cp_match.group(1))

            # Stockfish non fornisce WDL direttamente, lo stimiamo
            wdl = self._estimate_wdl(score_cp)

            # Estrai PV
            pv: list[str] = []
            pv_san: list[str] = []
            pv_match = pv_pattern.search(line)
            if pv_match:
                pv = pv_match.group(1).split()
                # Converti in SAN
                temp_board = board.copy()
                for move_uci in pv:
                    try:
                        move = chess.Move.from_uci(move_uci)
                        if move in temp_board.legal_moves:
                            pv_san.append(temp_board.san(move))
                            temp_board.push(move)
                        else:
                            break
                    except (ValueError, chess.InvalidMoveError):
                        break

            # Crea/aggiorna candidato
            if pv:
                move_uci = pv[0]
                try:
                    move = chess.Move.from_uci(move_uci)
                    move_san = board.san(move)
                except (ValueError, chess.InvalidMoveError):
                    continue

                candidates[mpv_idx] = MoveCandidate(
                    move=move_uci,
                    move_san=move_san,
                    score_cp=score_cp,
                    score_wdl=wdl,
                    pv=pv,
                    pv_san=pv_san,
                    nodes=nodes,
                    depth=depth,
                    policy=0.0,
                    rank=mpv_idx,
                    multipv_index=mpv_idx,
                )

        # Ordina candidati per rank
        sorted_candidates = [
            candidates[k] for k in sorted(candidates.keys()) if k in candidates
        ]

        # Valutazione globale dalla prima mossa
        evaluation_cp = sorted_candidates[0].score_cp if sorted_candidates else 0
        evaluation_wdl = sorted_candidates[0].score_wdl if sorted_candidates else (333, 334, 333)

        return PositionAnalysis(
            fen=fen,
            candidates=sorted_candidates,
            evaluation_cp=evaluation_cp,
            evaluation_wdl=evaluation_wdl,
            total_nodes=total_nodes,
            time_ms=time_ms,
            nps=nps,
            depth=max_depth,
            seldepth=max_seldepth,
            multipv=len(sorted_candidates),
        )

    def _estimate_wdl(self, score_cp: int) -> tuple[int, int, int]:
        """
        Stima Win/Draw/Loss da centipawns.

        Basato su formule empiriche di Stockfish.
        """
        # Sigmoid-like conversion
        import math

        # Normalizza score
        score = score_cp / 100.0

        # Probabilità vittoria (sigmoid)
        win_prob = 1.0 / (1.0 + math.exp(-score * 0.5))

        # Probabilità patta (più alta vicino a 0)
        draw_prob = 0.3 * math.exp(-abs(score) * 0.3)

        # Normalizza
        total = win_prob + draw_prob + (1 - win_prob)
        win = int((win_prob / total) * 1000)
        draw = int((draw_prob / total) * 1000)
        loss = 1000 - win - draw

        return (win, draw, loss)

    async def is_ready(self) -> bool:
        """Verifica se l'engine è pronto."""
        if not self._is_ready:
            return False

        async with self._lock:
            await self._send_command("isready")
            await self._wait_for("readyok")
            return True

    async def new_game(self) -> None:
        """Prepara l'engine per una nuova partita."""
        async with self._lock:
            await self._send_command("ucinewgame")
            await self._send_command("isready")
            await self._wait_for("readyok")

    @property
    def is_running(self) -> bool:
        """True se il processo Stockfish è in esecuzione."""
        return self._process is not None and self._process.returncode is None


async def create_stockfish(config: StockfishConfig) -> StockfishWrapper:
    """Factory function per creare e avviare Stockfish."""
    engine = StockfishWrapper(config)
    await engine.start()
    return engine
