async def update_tournament_match_winner(tournament_id: int, round_num: int, match_num: int, winner_id: str):
    """Atualiza o vencedor de uma partida do torneio e atribui pontos."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            with conn:
                # Atualiza o vencedor da partida
                cursor.execute('''
                    UPDATE tournament_matches SET winner_id = ?, status = 'finished', finished_at = CURRENT_TIMESTAMP
                    WHERE tournament_id = ? AND round_number = ? AND match_number = ?
                ''', (winner_id, tournament_id, round_num, match_num))

                # Atribui 1 ponto ao vencedor
                cursor.execute('''
                    UPDATE tournament_participants SET points = points + 1.0
                    WHERE tournament_id = ? AND player_id = ?
                ''', (tournament_id, winner_id))
        except Exception as e:
            print(f"Erro ao atualizar vencedor: {e}")
    await asyncio.to_thread(_update)

async def get_tournament_standings(tournament_id: int):
    """Busca a classificação atual do torneio por pontos."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tp.*, p.discord_username, p.lichess_username
            FROM tournament_participants tp
            JOIN players p ON tp.player_id = p.discord_id
            WHERE tp.tournament_id = ?
            ORDER BY tp.points DESC, tp.joined_at
        """, (tournament_id,))
        standings = cursor.fetchall()
        conn.close()
        return [dict(s) for s in standings]
    return await asyncio.to_thread(_get)

async def get_tournament_match_by_challenge(challenge_id: int):
    """Busca uma partida do torneio pelo ID do desafio."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tournament_matches WHERE challenge_id = ?", (challenge_id,))
        match = cursor.fetchone()
        conn.close()
        return dict(match) if match else None
    return await asyncio.to_thread(_get)

async def check_round_completion(tournament_id: int, round_num: int):
    """Verifica se todas as partidas de uma rodada foram finalizadas."""
    def _check():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'finished' THEN 1 END) as finished
            FROM tournament_matches WHERE tournament_id = ? AND round_number = ?
        """, (tournament_id, round_num))
        progress = cursor.fetchone()
        conn.close()
        return progress['total'] == progress['finished'] and progress['total'] > 0
    return await asyncio.to_thread(_check)
