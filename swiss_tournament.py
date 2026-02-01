import sqlite3
import logging
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)

DB_NAME = 'legion_chess.db'

def get_conn():
    """Cria uma conexão com o banco de dados."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

class SwissTournament:
    def __init__(self, tournament_id: int):
        self.tournament_id = tournament_id
        self.conn = get_conn()

    def close(self):
        self.conn.close()

    def get_tournament_info(self) -> Optional[Dict]:
        """Obtém informações do torneio Swiss."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM swiss_tournaments WHERE id = ?', (self.tournament_id,))
        return cursor.fetchone()

    def get_participants(self) -> List[Dict]:
        """Obtém todos os participantes do torneio."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT sp.*, p.discord_username, p.rating_blitz, p.rating_bullet, p.rating_rapid, p.rating_classic
            FROM swiss_participants sp
            LEFT JOIN players p ON sp.player_id = p.discord_id
            WHERE sp.tournament_id = ?
            ORDER BY sp.points DESC, sp.sonneborn_berger DESC, sp.tiebreak_score DESC, sp.wins DESC
        ''', (self.tournament_id,))
        results = cursor.fetchall()

        # Converter para dict e corrigir usernames vazios
        participants = []
        for result in results:
            participant = dict(result)
            if not participant['discord_username']:
                participant['discord_username'] = f"Player_{participant['player_id'][:8]}"
            participants.append(participant)

        return participants

    def get_player_record(self, player_id: str) -> Optional[Dict]:
        """Obtém o histórico e pontuação de um jogador no torneio."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM swiss_participants
            WHERE tournament_id = ? AND player_id = ?
        ''', (self.tournament_id, player_id))
        return cursor.fetchone()

    def get_pairings_for_round(self, round_number: int) -> List[Dict]:
        """Obtém todos os pairings de uma rodada específica."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT sp.*, p1.discord_username as player1_name, p2.discord_username as player2_name
            FROM swiss_pairings sp
            LEFT JOIN players p1 ON sp.player1_id = p1.discord_id
            LEFT JOIN players p2 ON sp.player2_id = p2.discord_id
            WHERE sp.tournament_id = ? AND sp.round_number = ?
            ORDER BY sp.id
        ''', (self.tournament_id, round_number))
        return cursor.fetchall()

    def get_player_history(self, player_id: str) -> List[Dict]:
        """Obtém o histórico de pairings de um jogador no torneio."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT * FROM swiss_pairings
            WHERE tournament_id = ? AND (player1_id = ? OR player2_id = ?)
            ORDER BY round_number
        ''', (self.tournament_id, player_id, player_id))
        return cursor.fetchall()

    def has_played(self, player1_id: str, player2_id: str) -> bool:
        """Verifica se dois jogadores já jogaram um contra o outro."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count FROM swiss_pairings
            WHERE tournament_id = ? AND (
                (player1_id = ? AND player2_id = ?) OR
                (player1_id = ? AND player2_id = ?)
            )
        ''', (self.tournament_id, player1_id, player2_id, player2_id, player1_id))
        result = cursor.fetchone()
        return result['count'] > 0

    def calculate_tiebreak(self, player_id: str) -> float:
        """
        Calcula o tiebreak score (Buchholz/Sum of Opposition Scores).
        Soma dos scores dos adversários já enfrentados.
        """
        opponents = []
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT player1_id, player2_id, winner_id FROM swiss_pairings
            WHERE tournament_id = ? AND status = 'finished' AND (player1_id = ? OR player2_id = ?)
        ''', (self.tournament_id, player_id, player_id))
        
        pairings = cursor.fetchall()
        for pairing in pairings:
            opponent_id = pairing['player2_id'] if pairing['player1_id'] == player_id else pairing['player1_id']
            opponent_record = self.get_player_record(opponent_id)
            if opponent_record:
                opponents.append(float(opponent_record['points']))
        
        return sum(opponents)

    def calculate_sonneborn_berger(self, player_id: str) -> float:
        """
        Calcula o Sonneborn-Berger (ponderado): soma dos pontos dos oponentes que você venceu
        mais metade dos pontos dos oponentes em que você empatou.
        """
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT player1_id, player2_id, winner_id FROM swiss_pairings
            WHERE tournament_id = ? AND status = 'finished' AND (player1_id = ? OR player2_id = ?)
        ''', (self.tournament_id, player_id, player_id))
        
        pairings = cursor.fetchall()
        sb_score = 0.0
        
        for pairing in pairings:
            is_player1 = pairing['player1_id'] == player_id
            opponent_id = pairing['player2_id'] if is_player1 else pairing['player1_id']
            winner_id = pairing['winner_id']
            
            opponent_record = self.get_player_record(opponent_id)
            if not opponent_record:
                continue
            
            opponent_points = float(opponent_record['points'])
            
            if winner_id == player_id:
                sb_score += opponent_points
            elif winner_id is None:
                sb_score += opponent_points * 0.5
        
        return sb_score

    def calculate_wins(self, player_id: str) -> int:
        """Retorna o número de vitórias do jogador."""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as wins FROM swiss_pairings
            WHERE tournament_id = ? AND winner_id = ?
        ''', (self.tournament_id, player_id))
        return cursor.fetchone()['wins']

    def generate_pairings(self, round_number: int) -> List[Tuple[str, Optional[str]]]:
        """
        Gera os pairings para a próxima rodada usando algoritmo Swiss.
        
        Retorna lista de tuplas (player1_id, player2_id) onde player2_id pode ser None para bye.
        """
        participants = self.get_participants()
        
        if not participants:
            return []

        if round_number == 1:
            return self._generate_first_round_pairings(participants)
        else:
            return self._generate_swiss_pairings(participants, round_number)

    def _generate_first_round_pairings(self, participants: List[Dict]) -> List[Tuple[str, Optional[str]]]:
        """Gera os pairings da primeira rodada (pareamento simples alternado)."""
        players = [p['player_id'] for p in participants]
        pairings = []

        for i in range(0, len(players), 2):
            if i + 1 < len(players):
                pairings.append((players[i], players[i + 1]))
            else:
                pairings.append((players[i], None))

        return pairings

    def _generate_swiss_pairings(self, participants: List[Dict], round_number: int) -> List[Tuple[str, Optional[str]]]:
        """
        Gera os pairings para rodadas subsequentes usando algoritmo Swiss modificado.
        
        Agrupa jogadores por pontuação e tenta aparear jogadores com pontos similares
        que não tenham jogado um contra o outro.
        """
        players = sorted(
            participants,
            key=lambda p: (-float(p['points']), -float(p['tiebreak_score']))
        )

        player_ids = [p['player_id'] for p in players]
        used = set()
        pairings = []

        for player_id in player_ids:
            if player_id in used:
                continue

            best_opponent = None
            for opponent_id in player_ids:
                if opponent_id == player_id or opponent_id in used:
                    continue

                if not self.has_played(player_id, opponent_id):
                    best_opponent = opponent_id
                    break
            
            if not best_opponent:
                for opponent_id in player_ids:
                    if opponent_id == player_id or opponent_id in used:
                        continue
                    best_opponent = opponent_id
                    break

            if best_opponent:
                pairings.append((player_id, best_opponent))
                used.add(player_id)
                used.add(best_opponent)

        return pairings

    def save_pairings(self, pairings: List[Tuple[str, Optional[str]]], round_number: int) -> bool:
        """Salva os pairings no banco de dados."""
        try:
            cursor = self.conn.cursor()
            
            for player1_id, player2_id in pairings:
                cursor.execute('''
                    INSERT INTO swiss_pairings
                    (tournament_id, round_number, player1_id, player2_id, status)
                    VALUES (?, ?, ?, ?, 'pending')
                ''', (self.tournament_id, round_number, player1_id, player2_id))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao salvar pairings: {e}")
            self.conn.rollback()
            return False

    def update_standings(self) -> bool:
        """Atualiza os standings (pontuação e todos os tiebreak criteria) de todos os participantes."""
        try:
            cursor = self.conn.cursor()
            participants = self.get_participants()

            for participant in participants:
                player_id = participant['player_id']

                cursor.execute('''
                    SELECT COUNT(*) as wins FROM swiss_pairings
                    WHERE tournament_id = ? AND winner_id = ?
                ''', (self.tournament_id, player_id))
                wins = cursor.fetchone()['wins']

                cursor.execute('''
                    SELECT COUNT(*) as draws FROM swiss_pairings
                    WHERE tournament_id = ? AND status = 'finished' AND 
                    (player1_id = ? OR player2_id = ?) AND winner_id IS NULL
                ''', (self.tournament_id, player_id, player_id))
                draws = cursor.fetchone()['draws']

                cursor.execute('''
                    SELECT COUNT(*) as losses FROM swiss_pairings
                    WHERE tournament_id = ? AND status = 'finished' AND 
                    (player1_id = ? OR player2_id = ?) AND winner_id IS NOT NULL AND winner_id != ?
                ''', (self.tournament_id, player_id, player_id, player_id))
                losses = cursor.fetchone()['losses']

                points = float(wins) + (float(draws) * 0.5)
                tiebreak = self.calculate_tiebreak(player_id)
                sonneborn_berger = self.calculate_sonneborn_berger(player_id)

                cursor.execute('''
                    UPDATE swiss_participants
                    SET points = ?, tiebreak_score = ?, sonneborn_berger = ?, 
                        wins = ?, draws = ?, losses = ?
                    WHERE tournament_id = ? AND player_id = ?
                ''', (points, tiebreak, sonneborn_berger, wins, draws, losses, 
                      self.tournament_id, player_id))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao atualizar standings: {e}")
            self.conn.rollback()
            return False

    def finish_pairing(self, pairing_id: int, winner_id: Optional[str], challenge_id: int) -> bool:
        """Marca um pairing como finalizado e atualiza o vencedor."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE swiss_pairings
                SET status = 'finished', winner_id = ?, challenge_id = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ? AND tournament_id = ?
            ''', (winner_id, challenge_id, pairing_id, self.tournament_id))

            self.conn.commit()
            self.update_standings()
            return True
        except Exception as e:
            logger.error(f"Erro ao finalizar pairing: {e}")
            self.conn.rollback()
            return False

    def finish_round(self, round_number: int) -> bool:
        """Marca todos os pairings de uma rodada como finalizados (se não estiverem ainda)."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT * FROM swiss_pairings
                WHERE tournament_id = ? AND round_number = ? AND status = 'pending'
            ''', (self.tournament_id, round_number))
            
            pending = cursor.fetchall()
            
            if pending:
                logger.warning(f"Ainda há pairings pendentes na rodada {round_number}")
                return False

            cursor.execute('''
                UPDATE swiss_tournaments
                SET current_round = ?
                WHERE id = ?
            ''', (round_number + 1, self.tournament_id))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao finalizar rodada: {e}")
            self.conn.rollback()
            return False

    def get_final_standings(self) -> List[Dict]:
        """Obtém o ranking final do torneio."""
        return self.get_participants()

    def finish_tournament(self) -> bool:
        """Marca o torneio como finalizado."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE swiss_tournaments
                SET status = 'finished', finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (self.tournament_id,))

            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Erro ao finalizar torneio: {e}")
            self.conn.rollback()
            return False
