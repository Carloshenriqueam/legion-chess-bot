import chess
import chess.pgn
from stockfish import Stockfish
import io
import os
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class GameAnalysis:
    """Análise de partida usando avaliações da API do Lichess"""
    
    def __init__(self, moves: list):
        self.moves = moves
        self.analysis: List[Dict[str, Any]] = []

    def _init_stockfish(self):
        """Initialize Stockfish lazily"""
        if self.stockfish is None:
            try:
                self.stockfish = Stockfish(self.stockfish_path)
            except Exception as e:
                logger.error(f"Erro ao inicializar Stockfish: {e}")
                raise

    def _eval_to_cp(self, eval_dict: Dict) -> int:
        """Convert evaluation to centipawns, handling mate"""
        if not eval_dict:
            return None
        if eval_dict.get('type') == 'cp':
            return int(eval_dict.get('value', 0))
        elif eval_dict.get('type') == 'mate':
            return None
        return None

    def analyze_game(self) -> List[Dict[str, Any]]:
        """Analyze the game using Lichess API evals"""
        total_moves = len(self.moves)
        logger.info(f"Analisando partida com {total_moves} movimentos usando avaliações da API do Lichess")

        prev_eval_cp = 0  # initial position eval
        prev_is_mate = False

        for idx, move in enumerate(self.moves):
            if not isinstance(move, dict):
                continue

            ply_counter = idx + 1
            move_uci = move.get('uci', '')
            eval_value = move.get('eval')
            mate_value = move.get('mate')

            if mate_value is not None:
                current_eval_cp = None
                current_is_mate = True
            else:
                current_eval_cp = eval_value
                current_is_mate = False

            best_move = move.get('best', '')  # if available in API

            if prev_eval_cp is None or current_eval_cp is None or prev_is_mate or current_is_mate:
                eval_change = None
                is_mate = True
            else:
                is_mate = False
                if ply_counter % 2 == 1:  # white moved
                    eval_change = prev_eval_cp - current_eval_cp
                else:  # black moved
                    eval_change = current_eval_cp - prev_eval_cp

            move_analysis = {
                'ply': ply_counter,
                'move': move_uci,
                'before_eval': {'cp': prev_eval_cp},
                'after_eval': {'cp': current_eval_cp, 'mate': mate_value},
                'before_eval_cp': prev_eval_cp,
                'after_eval_cp': current_eval_cp,
                'eval_change': eval_change,
                'is_mate': is_mate,
                'best_move': best_move,
                'is_best': move_uci == best_move if best_move else False
            }

            self.analysis.append(move_analysis)

            prev_eval_cp = current_eval_cp
            prev_is_mate = current_is_mate

            if (idx + 1) % 5 == 0:
                logger.debug(f"Progresso: {idx + 1}/{total_moves} movimentos analisados")

        logger.info(f"Análise concluída: {len(self.analysis)} movimentos analisados")
        return self.analysis

def get_stockfish_path():
    """Gets the path to the Stockfish executable from the .env file."""
    return os.getenv("STOCKFISH_PATH")
