# database.py
import sqlite3
import os
import asyncio
import json

DB_NAME = 'legion_chess.db'

def get_conn():
    """Cria uma conexão com o banco de dados e define row_factory."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

async def init_database():
    """Inicializa o banco de dados, criando as tabelas se não existirem."""
    conn = get_conn()
    cursor = conn.cursor()

    # Tabela de jogadores com múltiplos ratings
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS players (
        discord_id TEXT PRIMARY KEY,
        discord_username TEXT NOT NULL,
        lichess_username TEXT,
        rating INTEGER DEFAULT 1200, -- Rating geral antigo (opcional, pode ser removido)
        rating_bullet INTEGER DEFAULT 1200,
        rating_blitz INTEGER DEFAULT 1200,
        rating_rapid INTEGER DEFAULT 1200,
        rating_classic INTEGER DEFAULT 1200,
        wins_bullet INTEGER DEFAULT 0,
        losses_bullet INTEGER DEFAULT 0,
        draws_bullet INTEGER DEFAULT 0,
        wins_blitz INTEGER DEFAULT 0,
        losses_blitz INTEGER DEFAULT 0,
        draws_blitz INTEGER DEFAULT 0,
        wins_rapid INTEGER DEFAULT 0,
        losses_rapid INTEGER DEFAULT 0,
        draws_rapid INTEGER DEFAULT 0,
        wins_classic INTEGER DEFAULT 0,
        losses_classic INTEGER DEFAULT 0,
        draws_classic INTEGER DEFAULT 0
    )
    ''')

    # Tabela de desafios
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id TEXT NOT NULL,
        challenged_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        time_control TEXT NOT NULL,
        time_control_mode TEXT NOT NULL,
        is_rated INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        game_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (challenger_id) REFERENCES players(discord_id),
        FOREIGN KEY (challenged_id) REFERENCES players(discord_id)
    )
    ''')

    # Tabela de partidas finalizadas
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenge_id INTEGER NOT NULL,
        challenger_id TEXT NOT NULL,
        challenged_id TEXT NOT NULL,
        result TEXT NOT NULL,
        winner_id TEXT,
        pgn TEXT,
        finished_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (challenge_id) REFERENCES challenges(id),
        FOREIGN KEY (challenger_id) REFERENCES players(discord_id),
        FOREIGN KEY (challenged_id) REFERENCES players(discord_id)
    )
    ''')

    # Tabela para o puzzle diário ativo
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS active_puzzle (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        puzzle_id TEXT NOT NULL,
        pgn TEXT NOT NULL,
        first_move TEXT NOT NULL,
        color TEXT NOT NULL,
        solved_by TEXT,
        solved_at TIMESTAMP,
        announcement_message_id TEXT,
        FOREIGN KEY (solved_by) REFERENCES players(discord_id)
    )
    ''')

    # Tabela para configurações do servidor
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS server_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        fixed_ranking_channel_id TEXT,
        fixed_ranking_message_id TEXT
    )
    ''')

    # Tabela de torneios
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tournaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        mode TEXT NOT NULL, -- bullet, blitz, rapid, classic
        time_control TEXT NOT NULL,
        max_participants INTEGER DEFAULT 16,
        min_participants INTEGER DEFAULT 4,
        status TEXT DEFAULT 'open', -- open, closed, in_progress, finished
        created_by TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        finished_at TIMESTAMP,
        winner_id TEXT,
        is_automatic INTEGER DEFAULT 0,
        rated INTEGER DEFAULT 1,
        FOREIGN KEY (created_by) REFERENCES players(discord_id),
        FOREIGN KEY (winner_id) REFERENCES players(discord_id)
    )
    ''')

    # Tabela de participantes do torneio
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tournament_participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        player_id TEXT NOT NULL,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        eliminated INTEGER DEFAULT 0,
        position INTEGER,
        points REAL DEFAULT 0.0,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
        FOREIGN KEY (player_id) REFERENCES players(discord_id),
        UNIQUE(tournament_id, player_id)
    )
    ''')

    # Tabela de partidas do torneio
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tournament_matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        round_number INTEGER NOT NULL,
        match_number INTEGER NOT NULL,
        player1_id TEXT NOT NULL,
        player2_id TEXT,
        winner_id TEXT,
        challenge_id INTEGER,
        status TEXT DEFAULT 'pending', -- pending, in_progress, finished, bye
        scheduled_at TIMESTAMP,
        finished_at TIMESTAMP,
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id),
        FOREIGN KEY (player1_id) REFERENCES players(discord_id),
        FOREIGN KEY (player2_id) REFERENCES players(discord_id),
        FOREIGN KEY (winner_id) REFERENCES players(discord_id),
        FOREIGN KEY (challenge_id) REFERENCES challenges(id)
    )
    ''')
    
    # Adiciona coluna 'rated' se não existir (para compatibilidade com versões antigas)
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN rated INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass  # Coluna já existe

    conn.commit()
    conn.close()
    print("Banco de dados 'legion_chess.db' verificado/criado com sucesso.")

# ==============================================================================
# --- FUNÇÕES PARA JOGADORES ---
# ==============================================================================

async def register_player(discord_id: str, discord_username: str, lichess_username: str = None):
    """
    Registra um novo jogador.
    CORREÇÃO: Apenas insere as colunas necessárias. As colunas de rating usarão o valor DEFAULT.
    """
    def _register():
        conn = get_conn()
        cursor = conn.cursor()
        # O erro estava aqui: tínhamos 7 colunas e 8 valores.
        # A solução é inserir apenas os dados que temos e deixar o banco cuidar dos defaults.
        cursor.execute('''
            INSERT OR REPLACE INTO players (discord_id, discord_username, lichess_username)
            VALUES (?, ?, ?)
        ''', (discord_id, discord_username, lichess_username))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_register)

async def update_player_name(discord_id: str, new_name: str):
    """Atualiza o nome de um jogador no banco de dados."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE players SET discord_username = ? WHERE discord_id = ?", (new_name, discord_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def get_all_player_stats(discord_id: str):
    """Busca TODAS as estatísticas de um jogador pelo Discord ID."""
    def _fetch_stats():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE discord_id = ?", (discord_id,))
        player = cursor.fetchone()
        conn.close()
        return dict(player) if player else None
    return await asyncio.to_thread(_fetch_stats)

# ==============================================================================
# --- FUNÇÕES DE RATING INTERNO E RANKING ---
# ==============================================================================

async def update_rating_by_mode(discord_id: str, mode: str, new_rating: int):
    """Atualiza o rating de um jogador para uma modalidade específica."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE players SET rating_{mode} = ? WHERE discord_id = ?", (new_rating, discord_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def get_top_players_by_mode(mode: str, limit: int = None):
    """Busca os jogadores com maior rating para uma modalidade específica."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        # Se limit for None, busca todos os jogadores
        limit_clause = "" if limit is None else "LIMIT ?"
        params = () if limit is None else (limit,)

        cursor.execute(f'''
            SELECT discord_id, discord_username, lichess_username, rating_{mode} as rating, wins_{mode}+losses_{mode}+draws_{mode} as games
            FROM players
            WHERE rating_{mode} > 1000
            ORDER BY rating_{mode} DESC
            {limit_clause}
        ''', params)
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    return await asyncio.to_thread(_fetch)

# ==============================================================================
# --- FUNÇÕES PARA DESAFIOS ---
# ==============================================================================

def get_time_control_mode(time_str: str) -> str:
    """Converte uma string de tempo para o modo de jogo."""
    parts = time_str.split('+')
    initial_time = int(parts[0])
    if initial_time < 3:
        return 'bullet'
    elif initial_time < 8:
        return 'blitz'
    elif initial_time < 25:
        return 'rapid'
    else:
        return 'classic'

async def create_challenge(challenger_id: str, challenged_id: str, channel_id: str, time_control: str):
    mode = get_time_control_mode(time_control)
    def _create():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO challenges (challenger_id, challenged_id, channel_id, time_control, time_control_mode, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (challenger_id, challenged_id, channel_id, time_control, mode))
        challenge_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return challenge_id
    return await asyncio.to_thread(_create)

async def set_challenge_rated(challenge_id: int, is_rated: bool):
    """Define se um desafio vale rating ou não."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE challenges SET is_rated = ? WHERE id = ?", (is_rated, challenge_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def get_challenge(challenge_id: int):
    """Busca um desafio específico pelo ID."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM challenges WHERE id = ?", (challenge_id,))
        challenge = cursor.fetchone()
        conn.close()
        return dict(challenge) if challenge else None
    return await asyncio.to_thread(_fetch)

async def get_pending_challenges(discord_id: str):
    """Busca todos os desafios pendentes para um usuário."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM challenges WHERE challenged_id = ? AND status = 'pending'", (discord_id,))
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

async def update_challenge_status(challenge_id: int, status: str):
    """Atualiza o status de um desafio."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE challenges SET status = ? WHERE id = ?", (status, challenge_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def update_challenge_game_url(challenge_id: int, game_url: str):
    """Atualiza a URL do jogo de um desafio."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE challenges SET game_url = ? WHERE id = ?", (game_url, challenge_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def get_finished_games_to_process():
    """Busca desafios aceitos que ainda não foram finalizados no sistema."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, p1.discord_username as challenger_name, p2.discord_username as challenged_name,
                   p1.lichess_username as challenger_lichess_username, p2.lichess_username as challenged_lichess_username
            FROM challenges c
            JOIN players p1 ON c.challenger_id = p1.discord_id
            JOIN players p2 ON c.challenged_id = p2.discord_id
            WHERE c.status = 'accepted' AND c.game_url IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
        """)
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

async def mark_challenge_as_finished(challenge_id: int, winner_id: str, loser_id: str, result: str, pgn: str):
    """Marca um desafio como finalizado e salva a partida na tabela 'matches'."""
    def _mark():
        conn = get_conn()
        try:
            with conn:
                cursor = conn.cursor()
                # Atualiza o status do desafio
                cursor.execute("UPDATE challenges SET status = 'finished' WHERE id = ?", (challenge_id,))

                # CORREÇÃO: O INSERT estava incorreto. A versão abaixo seleciona os dados da tabela 'challenges'
                # e os insere na 'matches' de uma só vez, de forma segura.
                cursor.execute('''
                    INSERT INTO matches (challenge_id, challenger_id, challenged_id, result, winner_id, pgn)
                    SELECT id, challenger_id, challenged_id, ?, ?, ?
                    FROM challenges
                    WHERE id = ?
                ''', (result, winner_id, pgn, challenge_id))
        finally:
            conn.close()
    await asyncio.to_thread(_mark)

async def update_player_stats(discord_id: str, mode: str, result: str):
    """Atualiza as estatísticas de vitórias, derrotas ou empates de um jogador para uma modalidade."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        if result == 'win':
            cursor.execute(f"UPDATE players SET wins_{mode} = wins_{mode} + 1 WHERE discord_id = ?", (discord_id,))
        elif result == 'loss':
            cursor.execute(f"UPDATE players SET losses_{mode} = losses_{mode} + 1 WHERE discord_id = ?", (discord_id,))
        elif result == 'draw':
            cursor.execute(f"UPDATE players SET draws_{mode} = draws_{mode} + 1 WHERE discord_id = ?", (discord_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def get_challenge_by_game_url(game_url: str):
    """Busca um desafio pela URL do jogo."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM challenges WHERE game_url = ?", (game_url,))
        challenge = cursor.fetchone()
        conn.close()
        return dict(challenge) if challenge else None
    return await asyncio.to_thread(_fetch)

async def record_match_result(challenge_id: int, winner_discord_id: str, loser_discord_id: str, result: str, game_url: str):
    """Registra o resultado de uma partida."""
    def _record():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO matches (challenge_id, challenger_id, challenged_id, result, winner_id, pgn)
            SELECT id, challenger_id, challenged_id, ?, ?, ?
            FROM challenges
            WHERE id = ?
        ''', (result, winner_discord_id, game_url, challenge_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_record)

async def update_player_rating(discord_id: str, mode: str, result: str):
    """Atualiza o rating de um jogador baseado no resultado usando o sistema ELO."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        # Aqui você pode implementar a lógica de atualização de rating
        # Por exemplo, aumentar ou diminuir o rating baseado no resultado
        if result == 'win':
            cursor.execute(f"UPDATE players SET rating_{mode} = rating_{mode} + 10 WHERE discord_id = ?", (discord_id,))
        elif result == 'loss':
            cursor.execute(f"UPDATE players SET rating_{mode} = rating_{mode} - 10 WHERE discord_id = ?", (discord_id,))
        # Para empate, talvez não alterar ou alterar pouco
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def get_expired_challenges():
    """Busca desafios pendentes que expiraram (mais de 1 minuto)."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, p1.discord_username as challenger_name, p2.discord_username as challenged_name
            FROM challenges c
            JOIN players p1 ON c.challenger_id = p1.discord_id
            JOIN players p2 ON c.challenged_id = p2.discord_id
            WHERE c.status = 'pending'
            AND datetime(c.created_at) < datetime('now', '-1 minute')
        """)
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

# ==============================================================================
# --- FUNÇÕES PARA PUZZLES ---
# ==============================================================================

async def set_active_puzzle(puzzle_data: dict, message_id: str = None):
    """Salva o puzzle do dia no banco de dados."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO active_puzzle (id, puzzle_id, pgn, first_move, color, solved_by, solved_at, announcement_message_id)
            VALUES (1, ?, ?, ?, ?, NULL, NULL, ?)
        ''', (puzzle_data['puzzle_id'], puzzle_data['pgn'], puzzle_data['first_move'], puzzle_data['color'], message_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def get_active_puzzle():
    """Busca o puzzle do dia ativo."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_puzzle WHERE id = 1")
        puzzle = cursor.fetchone()
        conn.close()
        return dict(puzzle) if puzzle else None
    return await asyncio.to_thread(_get)

async def mark_puzzle_as_solved(discord_id: str):
    """Marca o puzzle como resolvido por um usuário."""
    def _mark():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE active_puzzle SET solved_by = ?, solved_at = CURRENT_TIMESTAMP WHERE id = 1", (discord_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_mark)

# ==============================================================================
# --- FUNÇÕES PARA CONFIGURAÇÕES DO SERVIDOR ---
# ==============================================================================

async def set_fixed_ranking_channel(channel_id: str):
    """Define o canal para o ranking fixo."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO server_settings (id, fixed_ranking_channel_id)
            VALUES (1, ?)
        ''', (channel_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def set_fixed_ranking_message(message_id: str):
    """Define a mensagem do ranking fixo."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE server_settings SET fixed_ranking_message_id = ? WHERE id = 1
        ''', (message_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def get_server_settings():
    """Busca as configurações do servidor."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM server_settings WHERE id = 1")
        settings = cursor.fetchone()
        conn.close()
        return dict(settings) if settings else None
    return await asyncio.to_thread(_get)

# ==============================================================================
# --- FUNÇÕES PARA TORNEIOS ---
# ==============================================================================

async def create_tournament(name: str, description: str, mode: str, time_control: str, max_participants: int, min_participants: int, created_by: str, is_automatic: bool = False, rated: bool = True):
    """Cria um novo torneio."""
    def _create():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO tournaments (name, description, mode, time_control, max_participants, min_participants, created_by, is_automatic, rated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, description, mode, time_control, max_participants, min_participants, created_by, is_automatic, rated))
        tournament_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return tournament_id
    return await asyncio.to_thread(_create)

async def get_tournament(tournament_id: int):
    """Busca um torneio específico."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        conn.close()
        return dict(tournament) if tournament else None
    return await asyncio.to_thread(_get)

async def get_open_tournaments():
    """Busca torneios abertos para inscrição."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tournaments WHERE status = 'open' ORDER BY created_at DESC")
        tournaments = cursor.fetchall()
        conn.close()
        return [dict(t) for t in tournaments]
    return await asyncio.to_thread(_get)

async def join_tournament(tournament_id: int, player_id: str):
    """Inscreve um jogador em um torneio."""
    def _join():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Verifica se o torneio existe e está aberto
            cursor.execute("SELECT * FROM tournaments WHERE id = ? AND status = 'open'", (tournament_id,))
            tournament = cursor.fetchone()
            if not tournament:
                return False, "Torneio não encontrado ou não está aberto para inscrições."

            # Verifica se já está inscrito
            cursor.execute("SELECT * FROM tournament_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            if cursor.fetchone():
                return False, "Você já está inscrito neste torneio."

            # Verifica limite de participantes
            cursor.execute("SELECT COUNT(*) as count FROM tournament_participants WHERE tournament_id = ?", (tournament_id,))
            count = cursor.fetchone()['count']
            if count >= tournament['max_participants']:
                return False, "Torneio já atingiu o limite máximo de participantes."

            # Inscreve o jogador
            cursor.execute('''
                INSERT INTO tournament_participants (tournament_id, player_id)
                VALUES (?, ?)
            ''', (tournament_id, player_id))
            conn.commit()
            return True, "Inscrição realizada com sucesso!"
        except Exception as e:
            conn.rollback()
            return False, f"Erro ao se inscrever: {str(e)}"
        finally:
            conn.close()
    return await asyncio.to_thread(_join)

async def get_tournament_participants(tournament_id: int):
    """Busca participantes de um torneio."""
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
        participants = cursor.fetchall()
        conn.close()
        return [dict(p) for p in participants]
    return await asyncio.to_thread(_get)

async def start_tournament(tournament_id: int):
    """Inicia um torneio, criando as partidas da primeira rodada."""
    def _start():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            with conn:
                # Busca participantes
                participants = cursor.execute("""
                    SELECT player_id FROM tournament_participants
                    WHERE tournament_id = ? ORDER BY joined_at
                """, (tournament_id,)).fetchall()

                if len(participants) < 2:
                    return False, "São necessários pelo menos 2 participantes para iniciar o torneio."

                # Embaralha participantes para bracket aleatório
                import random
                player_ids = [p['player_id'] for p in participants]
                random.shuffle(player_ids)

                # Cria partidas da primeira rodada
                round_num = 1
                match_num = 1
                for i in range(0, len(player_ids) - 1, 2):
                    player1 = player_ids[i]
                    player2 = player_ids[i + 1] if i + 1 < len(player_ids) else None

                    cursor.execute('''
                        INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, player2_id, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (tournament_id, round_num, match_num, player1, player2, 'pending' if player2 else 'bye'))

                    if player2:
                        # Cria desafio automático
                        challenge_id = cursor.execute('''
                            INSERT INTO challenges (challenger_id, challenged_id, channel_id, time_control, time_control_mode, status, is_rated)
                            SELECT ?, ?, '', t.time_control, t.mode, 'pending', 1
                            FROM tournaments t WHERE t.id = ?
                        ''', (player1, player2, tournament_id)).lastrowid

                        cursor.execute('''
                            UPDATE tournament_matches SET challenge_id = ? WHERE tournament_id = ? AND round_number = ? AND match_number = ?
                        ''', (challenge_id, tournament_id, round_num, match_num))

                    match_num += 1

                # Atualiza status do torneio
                cursor.execute("UPDATE tournaments SET status = 'in_progress', started_at = CURRENT_TIMESTAMP WHERE id = ?", (tournament_id,))

            return True, "Torneio iniciado com sucesso!"
        except Exception as e:
            return False, f"Erro ao iniciar torneio: {str(e)}"
    return await asyncio.to_thread(_start)

async def get_tournament_matches(tournament_id: int, round_num: int = None):
    """Busca partidas de um torneio."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        query = """
            SELECT tm.*, p1.discord_username as player1_name, p2.discord_username as player2_name,
                   c.game_url, c.status as challenge_status
            FROM tournament_matches tm
            LEFT JOIN players p1 ON tm.player1_id = p1.discord_id
            LEFT JOIN players p2 ON tm.player2_id = p2.discord_id
            LEFT JOIN challenges c ON tm.challenge_id = c.id
            WHERE tm.tournament_id = ?
        """
        params = [tournament_id]
        if round_num:
            query += " AND tm.round_number = ?"
            params.append(round_num)
        query += " ORDER BY tm.round_number, tm.match_number"

        cursor.execute(query, params)
        matches = cursor.fetchall()
        conn.close()
        return [dict(m) for m in matches]
    return await asyncio.to_thread(_get)

async def update_tournament_match_winner(tournament_id: int, round_num: int, match_num: int, winner_id: str):
    """Atualiza o vencedor de uma partida do torneio."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE tournament_matches SET winner_id = ?, status = 'finished', finished_at = CURRENT_TIMESTAMP
            WHERE tournament_id = ? AND round_number = ? AND match_number = ?
        ''', (winner_id, tournament_id, round_num, match_num))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

async def advance_tournament_round(tournament_id: int):
    """Avança para a próxima rodada do torneio."""
    def _advance():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            with conn:
                # Busca rodada atual
                cursor.execute("SELECT MAX(round_number) as current_round FROM tournament_matches WHERE tournament_id = ?", (tournament_id,))
                current_round = cursor.fetchone()['current_round'] or 0

                # Verifica se todas as partidas da rodada foram finalizadas
                cursor.execute("""
                    SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'finished' THEN 1 END) as finished
                    FROM tournament_matches WHERE tournament_id = ? AND round_number = ?
                """, (tournament_id, current_round))
                progress = cursor.fetchone()
                if progress['total'] != progress['finished']:
                    return False, "Nem todas as partidas da rodada atual foram finalizadas."

                # Busca vencedores da rodada atual
                winners = cursor.execute("""
                    SELECT winner_id FROM tournament_matches
                    WHERE tournament_id = ? AND round_number = ? AND winner_id IS NOT NULL
                    ORDER BY match_number
                """, (tournament_id, current_round)).fetchall()

                if len(winners) <= 1:
                    # Torneio finalizado
                    winner_id = winners[0]['winner_id'] if winners else None
                    cursor.execute("UPDATE tournaments SET status = 'finished', finished_at = CURRENT_TIMESTAMP, winner_id = ? WHERE id = ?", (winner_id, tournament_id))
                    return True, "Torneio finalizado!"

                # Cria próxima rodada
                next_round = current_round + 1
                winner_ids = [w['winner_id'] for w in winners]
                import random
                random.shuffle(winner_ids)

                match_num = 1
                for i in range(0, len(winner_ids) - 1, 2):
                    player1 = winner_ids[i]
                    player2 = winner_ids[i + 1] if i + 1 < len(winner_ids) else None

                    cursor.execute('''
                        INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, player2_id, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (tournament_id, next_round, match_num, player1, player2, 'pending' if player2 else 'bye'))

                    if player2:
                        # Cria desafio automático
                        challenge_id = cursor.execute('''
                            INSERT INTO challenges (challenger_id, challenged_id, channel_id, time_control, time_control_mode, status, is_rated)
                            SELECT ?, ?, '', t.time_control, t.mode, 'pending', 1
                            FROM tournaments t WHERE t.id = ?
                        ''', (player1, player2, tournament_id)).lastrowid

                        cursor.execute('''
                            UPDATE tournament_matches SET challenge_id = ? WHERE tournament_id = ? AND round_number = ? AND match_number = ?
                        ''', (challenge_id, tournament_id, next_round, match_num))

                    match_num += 1

            return True, f"Rodada {next_round} iniciada!"
        except Exception as e:
            return False, f"Erro ao avançar rodada: {str(e)}"
    return await asyncio.to_thread(_advance)
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

    """Busca a classificao atual do torneio por pontos."""

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

