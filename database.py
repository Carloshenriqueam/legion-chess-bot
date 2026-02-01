# database.py
import sqlite3
import os
import asyncio
import json
import logging
import threading
import queue
import datetime
import math

logger = logging.getLogger(__name__)

DB_NAME = 'legion_chess.db'

# Single-writer queue/worker to serialize DB writes and avoid SQLite "database is locked" under concurrency.
_write_queue = queue.Queue()
_writer_thread = None
_writer_loop = None

def _writer_worker(loop):
    """Worker thread that executes synchronous DB write callables from the queue.

    Each queue item is a tuple: (func, args, kwargs, asyncio.Future)
    The worker executes func(*args, **kwargs) and posts the result/exception
    back to the asyncio event loop via call_soon_threadsafe.
    """
    while True:
        func, args, kwargs, fut = _write_queue.get()
        try:
            res = func(*args, **kwargs)
            loop.call_soon_threadsafe(fut.set_result, res)
        except Exception as e:
            loop.call_soon_threadsafe(fut.set_exception, e)
        finally:
            _write_queue.task_done()


async def enqueue_write(func, *args, **kwargs):
    """Enqueue a synchronous callable to be executed by the DB writer thread.

    Returns the callable's return value.
    """
    global _writer_loop, _writer_thread
    if _writer_loop is None:
        # Should not happen if init_database was called; fallback to current loop.
        _writer_loop = asyncio.get_event_loop()
    loop = _writer_loop
    fut = loop.create_future()
    _write_queue.put((func, args, kwargs, fut))
    return await fut

def get_conn():
    """Cria uma conexão com o banco de dados e define row_factory."""
    # Usa timeout para esperar por locks e permite uso em threads diferentes.
    # Ativa WAL para melhorar concorrência entre leituras/escritas.
    conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        # Tenta ativar WAL (se já estiver não altera). Também garante chaves estrangeiras.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    return conn

async def init_database():
    """Inicializa o banco de dados, criando as tabelas se não existirem."""
    # Ensure writer thread is running and capture the asyncio loop reference
    global _writer_loop, _writer_thread
    if _writer_loop is None:
        _writer_loop = asyncio.get_event_loop()
    if _writer_thread is None or not _writer_thread.is_alive():
        _writer_thread = threading.Thread(target=_writer_worker, args=(_writer_loop,), daemon=True)
        _writer_thread.start()

    conn = get_conn()

    # Make a monthly backup of the DB file before applying any migrations/ALTERs
    try:
        if os.path.exists(DB_NAME):
            import shutil, datetime, glob
            
            # Check if we already have a backup for the current month
            current_month = datetime.datetime.utcnow().strftime('%Y%m')
            backup_pattern = f"{DB_NAME}.bak.{current_month}*"
            existing_backups = glob.glob(backup_pattern)
            
            if not existing_backups:
                # No backup for this month yet, create one
                bak_name = f"{DB_NAME}.bak.{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                shutil.copy2(DB_NAME, bak_name)
                logger.info(f"Backup mensal do DB criado: {bak_name}")
            else:
                # Backup already exists for this month
                latest_backup = max(existing_backups)
                logger.info(f"Backup mensal já existe para este mês: {latest_backup}")
    except Exception as e:
        logger.warning(f"Falha ao criar backup mensal do DB: {e}")
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

    # Migração: adicionar colunas agregadas gerais (wins, losses, draws)
    # Caso o banco existente não possua essas colunas, adiciona-as para compatibilidade.
    try:
        existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(players);").fetchall()]
        if 'wins' not in existing_cols:
            cursor.execute("ALTER TABLE players ADD COLUMN wins INTEGER DEFAULT 0")
        if 'losses' not in existing_cols:
            cursor.execute("ALTER TABLE players ADD COLUMN losses INTEGER DEFAULT 0")
        if 'draws' not in existing_cols:
            cursor.execute("ALTER TABLE players ADD COLUMN draws INTEGER DEFAULT 0")
        if 'avatar_hash' not in existing_cols:
            cursor.execute("ALTER TABLE players ADD COLUMN avatar_hash TEXT")
    except Exception:
        # Não bloquear a inicialização se a migração falhar aqui; logamos e seguimos.
        logger.warning("Migração: não foi possível verificar/adicionar colunas agregadas em players")

    # Tabela de desafios
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS challenges (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id TEXT NOT NULL,
        challenged_id TEXT NOT NULL,
        channel_id TEXT,
        time_control TEXT NOT NULL,
        time_control_mode TEXT NOT NULL,
        is_rated INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending',
        game_url TEXT,
        scheduled_at TIMESTAMP,
        tournament_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (challenger_id) REFERENCES players(discord_id),
        FOREIGN KEY (challenged_id) REFERENCES players(discord_id),
        FOREIGN KEY (tournament_id) REFERENCES tournaments(id)
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

    # Adiciona colunas de ranking se não existirem
    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN ranking_channel_id TEXT")
    except sqlite3.OperationalError:
        pass  # Coluna já existe

    try:
        cursor.execute("ALTER TABLE tournaments ADD COLUMN ranking_message_id TEXT")
    except sqlite3.OperationalError:
        pass  # Coluna já existe

    # Tabela para mapear canais de ranking por modo (ex: bullet, blitz, rapid, classic)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ranking_channels (
        mode TEXT PRIMARY KEY,
        channel_id TEXT NOT NULL,
        message_id TEXT
    )
    ''')

    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN wins INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN draws INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN losses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN sonneborn_berger REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN h2h_record TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # Tabela para histórico de partidas
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS game_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1_id TEXT NOT NULL,
        player2_id TEXT NOT NULL,
        player1_name TEXT,
        player2_name TEXT,
        winner_id TEXT,
        result TEXT NOT NULL,
        mode TEXT NOT NULL,
        time_control TEXT,
        game_url TEXT,
        player1_rating_before INTEGER,
        player2_rating_before INTEGER,
        player1_rating_after INTEGER,
        player2_rating_after INTEGER,
        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (player1_id) REFERENCES players(discord_id),
        FOREIGN KEY (player2_id) REFERENCES players(discord_id),
        FOREIGN KEY (winner_id) REFERENCES players(discord_id)
    )
    ''')

    # Tabela para histórico de ratings (para gráficos de evolução)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS rating_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT NOT NULL,
        mode TEXT NOT NULL,
        rating INTEGER NOT NULL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (player_id) REFERENCES players(discord_id)
    )
    ''')

    # Tabela para badges/achievements
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS achievements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT NOT NULL,
        achievement_type TEXT NOT NULL,
        achievement_name TEXT NOT NULL,
        description TEXT,
        value INTEGER DEFAULT 1,
        unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (player_id) REFERENCES players(discord_id),
        UNIQUE(player_id, achievement_type)
    )
    ''')

    # Tabela para record head-to-head entre jogadores
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS head_to_head (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1_id TEXT NOT NULL,
        player2_id TEXT NOT NULL,
        player1_wins INTEGER DEFAULT 0,
        player2_wins INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0,
        last_game_at TIMESTAMP,
        FOREIGN KEY (player1_id) REFERENCES players(discord_id),
        FOREIGN KEY (player2_id) REFERENCES players(discord_id),
        UNIQUE(player1_id, player2_id)
    )
    ''')

    # Tabelas para torneios Swiss
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS swiss_tournaments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        time_control TEXT NOT NULL,
        nb_rounds INTEGER NOT NULL,
        created_by TEXT NOT NULL,
        rated INTEGER DEFAULT 1,
        min_rating INTEGER,
        max_rating INTEGER,
        channel_id TEXT,
        status TEXT DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TIMESTAMP,
        finished_at TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS swiss_participants (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        player_id TEXT NOT NULL,
        points REAL DEFAULT 0.0,
        tiebreak_score REAL DEFAULT 0.0,
        sonneborn_berger REAL DEFAULT 0.0,
        h2h_record TEXT DEFAULT '',
        wins INTEGER DEFAULT 0,
        draws INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        FOREIGN KEY (tournament_id) REFERENCES swiss_tournaments(id),
        FOREIGN KEY (player_id) REFERENCES players(discord_id),
        UNIQUE(tournament_id, player_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS swiss_pairings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tournament_id INTEGER NOT NULL,
        round_number INTEGER NOT NULL,
        player1_id TEXT NOT NULL,
        player2_id TEXT,
        winner_id TEXT,
        challenge_id INTEGER,
        game_url TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        finished_at TIMESTAMP,
        FOREIGN KEY (tournament_id) REFERENCES swiss_tournaments(id),
        FOREIGN KEY (player1_id) REFERENCES players(discord_id),
        FOREIGN KEY (player2_id) REFERENCES players(discord_id),
        FOREIGN KEY (winner_id) REFERENCES players(discord_id),
        FOREIGN KEY (challenge_id) REFERENCES challenges(id)
    )
    ''')

    # Migrações para swiss_tournaments
    try:
        cursor.execute("ALTER TABLE swiss_tournaments ADD COLUMN description TEXT")
    except:
        pass  # Coluna já existe

    try:
        cursor.execute("ALTER TABLE swiss_tournaments ADD COLUMN channel_id TEXT")
    except:
        pass  # Coluna já existe

    # Migração para swiss_pairings
    try:
        cursor.execute("ALTER TABLE swiss_pairings ADD COLUMN game_url TEXT")
    except:
        pass  # Coluna já existe

    # Migração: adicionar coluna notified à tabela swiss_pairings para evitar duplicatas
    try:
        cursor.execute("ALTER TABLE swiss_pairings ADD COLUMN notified INTEGER DEFAULT 0")
    except:
        pass  # Coluna já existe

    # Migração especial: se swiss_tournaments tem esquema antigo, recriar
    try:
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(swiss_tournaments)").fetchall()]
        if 'max_players' in columns and 'time_control' not in columns:
            print("Detectado esquema antigo da tabela swiss_tournaments. Recriando...")
            # Backup dos dados existentes
            cursor.execute("CREATE TABLE swiss_tournaments_backup AS SELECT * FROM swiss_tournaments")
            # Drop e recriar
            cursor.execute("DROP TABLE swiss_tournaments")
            cursor.execute('''
            CREATE TABLE swiss_tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                time_control TEXT NOT NULL,
                nb_rounds INTEGER NOT NULL,
                created_by TEXT NOT NULL,
                rated INTEGER DEFAULT 1,
                min_rating INTEGER,
                max_rating INTEGER,
                channel_id TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
            ''')
            # Migrar dados (apenas campos comuns)
            cursor.execute('''
            INSERT INTO swiss_tournaments (id, name, description, channel_id, status, created_at, started_at, finished_at)
            SELECT id, name, description, channel_id, status, created_at, started_at, finished_at
            FROM swiss_tournaments_backup
            ''')
            cursor.execute("DROP TABLE swiss_tournaments_backup")
            print("Tabela swiss_tournaments recriada com esquema correto.")
        else:
            print("Esquema de swiss_tournaments já está correto.")
    except Exception as e:
        print(f"Aviso: erro na migração de swiss_tournaments: {e}")

    # Migração especial: se swiss_participants tem esquema antigo, recriar
    try:
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(swiss_participants)").fetchall()]
        if 'discord_id' in columns and 'player_id' not in columns:
            print("Detectado esquema antigo da tabela swiss_participants. Recriando...")
            # Backup dos dados existentes
            cursor.execute("CREATE TABLE swiss_participants_backup AS SELECT * FROM swiss_participants")
            # Drop e recriar
            cursor.execute("DROP TABLE swiss_participants")
            cursor.execute('''
            CREATE TABLE swiss_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                points REAL DEFAULT 0.0,
                tiebreak_score REAL DEFAULT 0.0,
                sonneborn_berger REAL DEFAULT 0.0,
                h2h_record TEXT DEFAULT '',
                wins INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                FOREIGN KEY (tournament_id) REFERENCES swiss_tournaments(id),
                FOREIGN KEY (player_id) REFERENCES players(discord_id),
                UNIQUE(tournament_id, player_id)
            )
            ''')
            # Migrar dados (mapeando discord_id para player_id, score para points)
            cursor.execute('''
            INSERT INTO swiss_participants (id, tournament_id, player_id, points, wins, draws, losses, sonneborn_berger, h2h_record)
            SELECT id, tournament_id, discord_id, score, wins, draws, losses, sonneborn_berger, h2h_record
            FROM swiss_participants_backup
            ''')
            cursor.execute("DROP TABLE swiss_participants_backup")
            print("Tabela swiss_participants recriada com esquema correto.")
    except Exception as e:
        print(f"Aviso: erro na migração de swiss_participants: {e}")

    # Migração: adicionar coluna scheduled_at à tabela challenges se não existir
    try:
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(challenges)").fetchall()]
        if 'scheduled_at' not in columns:
            print("Adicionando coluna scheduled_at à tabela challenges...")
            cursor.execute("ALTER TABLE challenges ADD COLUMN scheduled_at TIMESTAMP")
            print("Coluna scheduled_at adicionada com sucesso.")
    except Exception as e:
        print(f"Aviso: erro ao adicionar coluna scheduled_at: {e}")

    # Migração: adicionar colunas winner_id e loser_id à tabela challenges se não existirem
    try:
        columns = [row[1] for row in cursor.execute("PRAGMA table_info(challenges)").fetchall()]
        if 'winner_id' not in columns:
            print("Adicionando coluna winner_id à tabela challenges...")
            cursor.execute("ALTER TABLE challenges ADD COLUMN winner_id TEXT")
            print("Coluna winner_id adicionada com sucesso.")
        if 'loser_id' not in columns:
            print("Adicionando coluna loser_id à tabela challenges...")
            cursor.execute("ALTER TABLE challenges ADD COLUMN loser_id TEXT")
            print("Coluna loser_id adicionada com sucesso.")
    except Exception as e:
        print(f"Aviso: erro ao adicionar colunas winner_id/loser_id: {e}")

    conn.commit()
    conn.close()
    print("Banco de dados 'legion_chess.db' verificado/criado com sucesso.")

# ==============================================================================
# --- FUNÇÕES PARA JOGADORES ---
# ==============================================================================

async def register_player(discord_id: str, discord_username: str, lichess_username: str = None):
    """
    Registra um novo jogador e atribui o achievement padrão.
    """
    def _register():
        conn = get_conn()
        cursor = conn.cursor()
        # Inserir ou atualizar o jogador
        cursor.execute('''
            INSERT OR REPLACE INTO players (discord_id, discord_username, lichess_username)
            VALUES (?, ?, ?)
        ''', (discord_id, discord_username, lichess_username))
        
        # Desbloquear o achievement padrão
        cursor.execute('''
            INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
            VALUES (?, 'default', 'Membro Verificado', 'Se registrou no bot')
        ''', (discord_id,))
        
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

async def cancel_challenge(challenge_id: int, cancelled_by: str):
    """Cancela um desafio devido a aborto."""
    def _cancel():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE challenges SET status = 'cancelled' WHERE id = ?", (challenge_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_cancel)

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

async def get_player_by_discord_id(discord_id: str):
    """Busca os dados básicos de um jogador pelo Discord ID."""
    def _fetch_player():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT discord_id, discord_username, lichess_username FROM players WHERE discord_id = ?", (discord_id,))
        player = cursor.fetchone()
        conn.close()
        return dict(player) if player else None
    return await asyncio.to_thread(_fetch_player)

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

async def create_challenge(challenger_id: str, challenged_id: str, channel_id: str, time_control: str, scheduled_at: str = None, tournament_id: int = None):
    mode = get_time_control_mode(time_control)
    status = 'scheduled' if scheduled_at else 'pending'
    logger.info(f"📝 Criando desafio: challenger={challenger_id}, challenged={challenged_id}, scheduled_at={scheduled_at}, status={status}")
    def _create():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO challenges (challenger_id, challenged_id, channel_id, time_control, time_control_mode, status, scheduled_at, tournament_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (challenger_id, challenged_id, channel_id, time_control, mode, status, scheduled_at, tournament_id))
        challenge_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return challenge_id

    return await enqueue_write(_create)

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


async def get_pending_challenge_between_players(challenger_id: str, challenged_id: str):
    """Busca um desafio pendente entre dois jogadores, em qualquer direção (A->B ou B->A)."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM challenges WHERE status = 'pending' AND ((challenger_id = ? AND challenged_id = ?) OR (challenger_id = ? AND challenged_id = ?)) ORDER BY created_at DESC LIMIT 1",
            (challenger_id, challenged_id, challenged_id, challenger_id)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
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
    """Busca desafios aceitos que ainda não foram finalizados no sistema e desafios finalizados sem histórico."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()

        # Buscar desafios normais (aceitos e ainda não processados, ou finalizados sem histórico)
        cursor.execute("""
            SELECT c.*, p1.discord_username as challenger_name, p2.discord_username as challenged_name,
                   p1.lichess_username as challenger_lichess_username, p2.lichess_username as challenged_lichess_username,
                   NULL as swiss_pairing_id
            FROM challenges c
            JOIN players p1 ON c.challenger_id = p1.discord_id
            JOIN players p2 ON c.challenged_id = p2.discord_id
            WHERE (
                -- Desafios aceitos que ainda não foram salvos em game_history
                (c.status = 'accepted' AND c.game_url IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id))
                OR
                -- Desafios finalizados que ainda não foram salvos em game_history
                (c.status = 'finished' AND c.game_url IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM game_history g WHERE g.game_url = c.game_url))
            )
        """)
        challenges = cursor.fetchall()

        # Buscar jogos de torneios suíços que ainda não foram processados
        swiss_games = []
        try:
            cursor.execute("""
                SELECT sp.game_url, sp.tournament_id, sp.round_number, sp.player1_id, sp.player2_id,
                       p1.discord_username as player1_name, p2.discord_username as player2_name,
                       p1.lichess_username as player1_lichess, p2.lichess_username as player2_lichess,
                       sp.id as swiss_pairing_id,
                       NULL as id, NULL as challenger_id, NULL as challenged_id, NULL as time_control,
                       NULL as time_control_mode, NULL as is_rated, NULL as status
                FROM swiss_pairings sp
                JOIN players p1 ON sp.player1_id = p1.discord_id
                JOIN players p2 ON sp.player2_id = p2.discord_id
                WHERE sp.game_url IS NOT NULL
                AND sp.winner_id IS NULL
                AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.game_url = sp.game_url)
            """)
            swiss_games = cursor.fetchall()
        except sqlite3.OperationalError:
            # Tabela swiss_pairings ainda não existe (nenhum torneio suíço foi criado)
            pass

        # Combinar resultados
        all_games = challenges + swiss_games
        conn.close()
        return [dict(game) for game in all_games]
    return await asyncio.to_thread(_fetch)

async def mark_challenge_as_finished(challenge_id: int, winner_id: str, loser_id: str, result: str, pgn: str):
    """Marca um desafio como finalizado e salva a partida na tabela 'matches'."""
    def _mark():
        conn = get_conn()
        try:
            with conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE challenges SET status = 'finished', winner_id = ?, loser_id = ? WHERE id = ?", (winner_id, loser_id, challenge_id))
                cursor.execute('''
                    INSERT INTO matches (challenge_id, challenger_id, challenged_id, result, winner_id, pgn)
                    SELECT id, challenger_id, challenged_id, ?, ?, ?
                    FROM challenges
                    WHERE id = ?
                ''', (result, winner_id, pgn, challenge_id))
        finally:
            conn.close()

    await enqueue_write(_mark)

async def update_player_stats(discord_id: str, mode: str, result: str):
    """Atualiza as estatísticas de vitórias, derrotas ou empates de um jogador para uma modalidade e total geral."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        if result == 'win':
            cursor.execute(f"UPDATE players SET wins_{mode} = wins_{mode} + 1 WHERE discord_id = ?", (discord_id,))
            cursor.execute("UPDATE players SET wins = wins + 1 WHERE discord_id = ?", (discord_id,))
        elif result == 'loss':
            cursor.execute(f"UPDATE players SET losses_{mode} = losses_{mode} + 1 WHERE discord_id = ?", (discord_id,))
            cursor.execute("UPDATE players SET losses = losses + 1 WHERE discord_id = ?", (discord_id,))
        elif result == 'draw':
            cursor.execute(f"UPDATE players SET draws_{mode} = draws_{mode} + 1 WHERE discord_id = ?", (discord_id,))
            cursor.execute("UPDATE players SET draws = draws + 1 WHERE discord_id = ?", (discord_id,))
        conn.commit()
        conn.close()

    await enqueue_write(_update)

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

async def apply_match_ratings(winner_id: str, loser_id: str, mode: str):
    """Aplica mudanças de rating ELO entre dois jogadores após uma partida."""
    def _apply():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT rating_{mode} FROM players WHERE discord_id = ?", (winner_id,))
            winner_rating_row = cursor.fetchone()
            cursor.execute(f"SELECT rating_{mode} FROM players WHERE discord_id = ?", (loser_id,))
            loser_rating_row = cursor.fetchone()

            if not winner_rating_row or not loser_rating_row:
                logger.warning(f"Não foi possível encontrar ratings para {winner_id} ou {loser_id}")
                return None

            winner_rating = winner_rating_row[0] or 1200
            loser_rating = loser_rating_row[0] or 1200

            winner_expected = 1 / (1 + 10 ** ((loser_rating - winner_rating) / 400))
            loser_expected = 1 / (1 + 10 ** ((winner_rating - loser_rating) / 400))

            k_factor = 32

            winner_change = round(k_factor * (1 - winner_expected))
            loser_change = round(k_factor * (0 - loser_expected))

            new_winner_rating = winner_rating + winner_change
            new_loser_rating = loser_rating + loser_change

            cursor.execute(f"UPDATE players SET rating_{mode} = ? WHERE discord_id = ?", (new_winner_rating, winner_id))
            cursor.execute(f"UPDATE players SET rating_{mode} = ? WHERE discord_id = ?", (new_loser_rating, loser_id))

            conn.commit()

            return {
                'winner': {
                    'old_rating': winner_rating,
                    'new_rating': new_winner_rating,
                    'change': winner_change
                },
                'loser': {
                    'old_rating': loser_rating,
                    'new_rating': new_loser_rating,
                    'change': loser_change
                }
            }

        except Exception as e:
            logger.error(f"Erro ao aplicar mudanças de rating: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    return await enqueue_write(_apply)

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
            AND c.scheduled_at IS NULL
            AND datetime(c.created_at) < datetime('now', '-1 minute')
        """)
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

async def get_scheduled_challenges_ready():
    """Busca desafios agendados que estão prontos para serem ativados (hora atual >= scheduled_at)."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, p1.discord_username as challenger_name, p2.discord_username as challenged_name
            FROM challenges c
            JOIN players p1 ON c.challenger_id = p1.discord_id
            JOIN players p2 ON c.challenged_id = p2.discord_id
            WHERE c.status = 'scheduled'
            AND datetime(c.scheduled_at) <= datetime('now')
        """)
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

async def get_scheduled_challenges_for_player(discord_id: str):
    """Busca desafios agendados para um jogador específico."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.*, p1.discord_username as challenger_name, p2.discord_username as challenged_name
            FROM challenges c
            JOIN players p1 ON c.challenger_id = p1.discord_id
            JOIN players p2 ON c.challenged_id = p2.discord_id
            WHERE c.status = 'scheduled'
            AND (c.challenger_id = ? OR c.challenged_id = ?)
            AND datetime(c.scheduled_at) > datetime('now')
            ORDER BY c.scheduled_at ASC
        """, (discord_id, discord_id))
        challenges = cursor.fetchall()
        conn.close()
        return [dict(c) for c in challenges]
    return await asyncio.to_thread(_fetch)

async def activate_scheduled_challenge(challenge_id: int):
    """Ativa um desafio agendado mudando seu status para 'pending'."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE challenges SET status = 'pending' WHERE id = ?", (challenge_id,))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_update)

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


async def set_ranking_channel(mode: str, channel_id: str, message_id: str = None):
    """Define ou atualiza o canal (e mensagem opcional) usado para exibir o ranking de um modo específico."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO ranking_channels (mode, channel_id, message_id)
                VALUES (?, ?, ?)
                ON CONFLICT(mode) DO UPDATE SET channel_id=excluded.channel_id, message_id=excluded.message_id
            ''', (mode, channel_id, message_id))
            conn.commit()
        finally:
            conn.close()
    return await asyncio.to_thread(_set)


async def get_ranking_channel(mode: str):
    """Retorna a tupla (mode, channel_id, message_id) para o modo informado ou None."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT mode, channel_id, message_id FROM ranking_channels WHERE mode = ?", (mode,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    return await asyncio.to_thread(_get)


async def get_all_ranking_channels():
    """Retorna uma lista de todos os canais de ranking configurados: [{'mode', 'channel_id', 'message_id'}, ...]"""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT mode, channel_id, message_id FROM ranking_channels")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_get)


async def remove_ranking_channel(mode: str):
    """Remove a configuração de canal de ranking para um modo específico."""
    def _remove():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ranking_channels WHERE mode = ?", (mode,))
        conn.commit()
        conn.close()
    return await asyncio.to_thread(_remove)

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
    return await enqueue_write(_create)
    

async def create_swiss_tournament(name: str, description: str, time_control: str, nb_rounds: int, created_by: str, rated: bool = True, min_rating: int = None, max_rating: int = None, channel_id: str = None):
    """Cria um novo torneio Swiss."""
    def _create():
        conn = get_conn()
        cursor = conn.cursor()

        # Create tables if they do not exist (in case init_database missed them)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS swiss_tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                time_control TEXT NOT NULL,
                nb_rounds INTEGER NOT NULL,
                created_by TEXT NOT NULL,
                rated INTEGER DEFAULT 1,
                min_rating INTEGER,
                max_rating INTEGER,
                channel_id TEXT,
                status TEXT DEFAULT 'open',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS swiss_participants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                player_id TEXT NOT NULL,
                points REAL DEFAULT 0.0,
                tiebreak_score REAL DEFAULT 0.0,
                sonneborn_berger REAL DEFAULT 0.0,
                h2h_record TEXT DEFAULT '',
                wins INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                FOREIGN KEY (tournament_id) REFERENCES swiss_tournaments(id),
                FOREIGN KEY (player_id) REFERENCES players(discord_id),
                UNIQUE(tournament_id, player_id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS swiss_pairings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tournament_id INTEGER NOT NULL,
                round_number INTEGER NOT NULL,
                player1_id TEXT NOT NULL,
                player2_id TEXT,
                winner_id TEXT,
                challenge_id INTEGER,
                game_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                FOREIGN KEY (tournament_id) REFERENCES swiss_tournaments(id),
                FOREIGN KEY (player1_id) REFERENCES players(discord_id),
                FOREIGN KEY (player2_id) REFERENCES players(discord_id),
                FOREIGN KEY (winner_id) REFERENCES players(discord_id),
                FOREIGN KEY (challenge_id) REFERENCES challenges(id)
            )
        ''')

        # Adicionar coluna channel_id se não existir (para migração)
        try:
            cursor.execute("ALTER TABLE swiss_tournaments ADD COLUMN channel_id TEXT")
        except:
            pass  # Coluna já existe

        # Adicionar coluna description se não existir (para migração)
        try:
            cursor.execute("ALTER TABLE swiss_tournaments ADD COLUMN description TEXT")
        except:
            pass  # Coluna já existe

        # Adicionar coluna game_url se não existir (para migração)
        try:
            cursor.execute("ALTER TABLE swiss_pairings ADD COLUMN game_url TEXT")
        except:
            pass  # Coluna já existe

        cursor.execute('''
            INSERT INTO swiss_tournaments (name, description, time_control, nb_rounds, created_by, rated, min_rating, max_rating, channel_id, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        ''', (name, description, time_control, nb_rounds, created_by, int(rated), min_rating, max_rating, channel_id))
        tournament_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return tournament_id

    return await enqueue_write(_create)

async def get_swiss_tournament(tournament_id: int):
    """Busca um torneio Swiss específico."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM swiss_tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        conn.close()
        return dict(tournament) if tournament else None
    return await asyncio.to_thread(_get)

async def get_swiss_tournament_participants(tournament_id: int):
    """Busca participantes de um torneio Swiss."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sp.*, p.discord_username, p.lichess_username
            FROM swiss_participants sp
            LEFT JOIN players p ON sp.player_id = p.discord_id
            WHERE sp.tournament_id = ?
            ORDER BY sp.points DESC, sp.tiebreak_score DESC
        """, (tournament_id,))
        results = cursor.fetchall()
        conn.close()

        # Converter para dict e corrigir usernames vazios
        participants = []
        for result in results:
            participant = dict(result)
            if not participant['discord_username']:
                participant['discord_username'] = f"Player_{participant['player_id'][:8]}"
            participants.append(participant)

        return participants
    return await asyncio.to_thread(_get)

async def abandon_swiss_tournament(tournament_id: int, player_id: str):
    """Remove um jogador do torneio."""
    def _abandon():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Remove o jogador do torneio
            cursor.execute("""
                DELETE FROM swiss_participants 
                WHERE tournament_id = ? AND player_id = ?
            """, (tournament_id, player_id))
            
            conn.commit()
            logger.info(f"Jogador {player_id} removido do torneio {tournament_id}")
            return True, "Você foi removido do torneio."
        except Exception as e:
            logger.error(f"Erro ao abandonar torneio: {e}")
            return False, f"Erro ao processar abandono: {e}"
        finally:
            conn.close()
    
    return await asyncio.to_thread(_abandon)

async def process_abandoned_games(tournament_id: int, player_id: str):
    """Marca todas as partidas restantes do jogador como perdidas."""
    def _process():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Buscar todas as partidas não finalizadas do jogador
            cursor.execute("""
                SELECT * FROM swiss_pairings 
                WHERE tournament_id = ? 
                AND (player1_id = ? OR player2_id = ?)
                AND status != 'finished'
            """, (tournament_id, player_id, player_id))
            
            unfinished_games = cursor.fetchall()
            
            for game in unfinished_games:
                game = dict(game)
                # Determina o oponente
                opponent_id = game['player2_id'] if game['player1_id'] == player_id else game['player1_id']
                
                # Pula se o oponente é None (bye)
                if not opponent_id:
                    logger.debug(f"Pairing {game['id']}: Jogador abandonado tinha bye, nada a fazer")
                    continue
                
                logger.debug(f"Pairing {game['id']}: Marcando {opponent_id} como vencedor (abandonante: {player_id})")
                
                # Marca o oponente como vencedor
                cursor.execute("""
                    UPDATE swiss_pairings 
                    SET winner_id = ?, status = 'finished'
                    WHERE id = ?
                """, (opponent_id, game['id']))
                
                # Verifica se o oponente ainda está no torneio
                cursor.execute("""
                    SELECT * FROM swiss_participants 
                    WHERE tournament_id = ? AND player_id = ?
                """, (tournament_id, opponent_id))
                
                if cursor.fetchone():
                    # Atualiza standings do oponente
                    cursor.execute("""
                        UPDATE swiss_participants 
                        SET points = points + 1.0, wins = wins + 1
                        WHERE tournament_id = ? AND player_id = ?
                    """, (tournament_id, opponent_id))
                    logger.info(f"Pairing {game['id']}: +1 ponto para {opponent_id}")
                else:
                    logger.warning(f"Pairing {game['id']}: Oponente {opponent_id} não está mais no torneio")
            
            conn.commit()
            logger.info(f"Jogador {player_id}: {len(unfinished_games)} partidas marcadas como perdidas no torneio {tournament_id}")
        except Exception as e:
            logger.error(f"Erro ao processar partidas abandonadas: {e}", exc_info=True)
        finally:
            conn.close()
    
    await asyncio.to_thread(_process)

async def join_swiss_tournament(tournament_id: int, player_id: str):
    """Inscreve um jogador em um torneio Swiss."""
    def _join():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Garante que o jogador existe na tabela players
            cursor.execute('''
                INSERT OR IGNORE INTO players (discord_id, discord_username)
                VALUES (?, ?)
            ''', (player_id, f"Player_{player_id[:8]}"))

            # Verifica se o jogador está registrado (tem lichess_username)
            cursor.execute("SELECT lichess_username FROM players WHERE discord_id = ?", (player_id,))
            player_data = cursor.fetchone()
            if not player_data or not player_data['lichess_username']:
                return False, "Você precisa se registrar primeiro! Use `/registrar <seu_usuario_lichess>` para conectar sua conta do Lichess."

            # Verifica se o torneio existe e está aberto
            cursor.execute("SELECT * FROM swiss_tournaments WHERE id = ? AND status = 'open'", (tournament_id,))
            tournament = cursor.fetchone()
            if not tournament:
                return False, "Torneio não encontrado ou não está aberto para inscrições."

            # Verifica se já está inscrito
            cursor.execute("SELECT * FROM swiss_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            if cursor.fetchone():
                return False, "Você já está inscrito neste torneio."

            # Verifica limites de rating se aplicáveis
            if tournament['min_rating'] or tournament['max_rating']:
                cursor.execute("SELECT rating_blitz FROM players WHERE discord_id = ?", (player_id,))
                player_rating = cursor.fetchone()
                if player_rating:
                    rating = player_rating['rating_blitz']
                    if tournament['min_rating'] and rating < tournament['min_rating']:
                        return False, f"Seu rating é muito baixo. Mínimo requerido: {tournament['min_rating']}"
                    if tournament['max_rating'] and rating > tournament['max_rating']:
                        return False, f"Seu rating é muito alto. Máximo permitido: {tournament['max_rating']}"

            # Inscreve o jogador
            cursor.execute('''
                INSERT INTO swiss_participants (tournament_id, player_id)
                VALUES (?, ?)
            ''', (tournament_id, player_id))
            conn.commit()
            return True, "Inscrição realizada com sucesso!"
        except Exception as e:
            conn.rollback()
            return False, f"Erro ao se inscrever: {str(e)}"
        finally:
            conn.close()
    return await enqueue_write(_join)

async def leave_swiss_tournament(tournament_id: int, player_id: str):
    """Remove a inscrição de um jogador em um torneio Swiss."""
    def _leave():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Verifica se o participante está inscrito
            cursor.execute("SELECT * FROM swiss_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            if not cursor.fetchone():
                return False, "Você não está inscrito neste torneio."

            cursor.execute("DELETE FROM swiss_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            conn.commit()
            return True, "Removido da inscrição com sucesso."
        except Exception as e:
            conn.rollback()
            return False, f"Erro ao remover inscrição: {str(e)}"
        finally:
            conn.close()

    return await enqueue_write(_leave)

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

async def get_tournaments_by_status(status: str):
    """Busca torneios por status específico."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM tournaments WHERE status = ? ORDER BY created_at DESC", (status,))
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
    return await enqueue_write(_join)


async def leave_tournament(tournament_id: int, player_id: str):
    """Remove a inscrição de um jogador em um torneio."""
    def _leave():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Verifica se o participante está inscrito
            cursor.execute("SELECT * FROM tournament_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            if not cursor.fetchone():
                return False, "Você não está inscrito neste torneio."

            cursor.execute("DELETE FROM tournament_participants WHERE tournament_id = ? AND player_id = ?", (tournament_id, player_id))
            conn.commit()
            return True, "Removido da inscrição com sucesso."
        except Exception as e:
            conn.rollback()
            return False, f"Erro ao remover inscrição: {str(e)}"
        finally:
            conn.close()

    return await enqueue_write(_leave)



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

async def start_bracket_tournament(tournament_id: int, channel_id: str = None):
    """Inicia um torneio de bracket, lidando com byes para potências de 2."""
    def _start_bracket():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            with conn:
                # Busca participantes
                participants = cursor.execute("""
                    SELECT player_id FROM tournament_participants
                    WHERE tournament_id = ? ORDER BY joined_at
                """, (tournament_id,)).fetchall()

                num_participants = len(participants)
                if num_participants < 2:
                    return False, "São necessários pelo menos 2 participantes para iniciar o torneio."

                # Embaralha participantes
                import random
                player_ids = [p['player_id'] for p in participants]
                # Seed aleatório
                random.shuffle(player_ids)

                # Calcula a próxima potência de 2
                next_power_of_two = 2**math.ceil(math.log2(num_participants))
                num_byes = next_power_of_two - num_participants

                # Separa quem ganha Bye e quem joga
                # Em um bracket aleatório, os primeiros 'num_byes' jogadores avançam direto
                players_getting_bye = player_ids[:num_byes]
                players_playing = player_ids[num_byes:]
                
                match_num = 1

                # 1. Cria partidas de Bye (Rodada 1) - Jogador vs NULL
                for player_id in players_getting_bye:
                    cursor.execute('''
                        INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, winner_id, status)
                        VALUES (?, 1, ?, ?, ?, 'finished')
                    ''', (tournament_id, match_num, player_id, player_id))
                    match_num += 1

                # 2. Cria partidas normais (Rodada 1) - Jogador vs Jogador
                for i in range(0, len(players_playing), 2):
                    player1 = players_playing[i]
                    player2 = players_playing[i+1]

                    cursor.execute('''
                        INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, player2_id, status)
                        VALUES (?, 1, ?, ?, ?, 'pending')
                    ''', (tournament_id, match_num, player1, player2))
                    
                    # Associa desafio com channel_id
                    challenge_id = cursor.execute('''
                        INSERT INTO challenges (challenger_id, challenged_id, channel_id, tournament_id, time_control, time_control_mode, status, is_rated)
                        SELECT ?, ?, ?, ?, t.time_control, t.mode, 'pending', t.rated
                        FROM tournaments t WHERE t.id = ?
                    ''', (player1, player2, channel_id or '', tournament_id, tournament_id)).lastrowid

                    cursor.execute('''
                        UPDATE tournament_matches SET challenge_id = ?
                        WHERE tournament_id = ? AND round_number = 1 AND match_number = ?
                    ''', (challenge_id, tournament_id, match_num))
                    
                    match_num += 1

                # Atualiza status do torneio
                cursor.execute("UPDATE tournaments SET status = 'in_progress', started_at = CURRENT_TIMESTAMP WHERE id = ?", (tournament_id,))
                
            return True, "Torneio iniciado com sucesso!"
        except Exception as e:
            logger.error(f"Erro ao iniciar torneio de bracket: {e}", exc_info=True)
            return False, f"Erro ao iniciar torneio de bracket: {e}"

    return await enqueue_write(_start_bracket)


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
    """Avança para a próxima rodada do torneio, mantendo estrutura de bracket."""
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

                # Busca vencedores da rodada atual ordenados por match_number para manter estrutura de bracket
                winners = cursor.execute("""
                    SELECT winner_id, match_number FROM tournament_matches
                    WHERE tournament_id = ? AND round_number = ? AND winner_id IS NOT NULL
                    ORDER BY match_number
                """, (tournament_id, current_round)).fetchall()

                if len(winners) <= 1:
                    # Torneio finalizado
                    winner_id = winners[0]['winner_id'] if winners else None
                    cursor.execute("UPDATE tournaments SET status = 'finished', finished_at = CURRENT_TIMESTAMP, winner_id = ? WHERE id = ?", (winner_id, tournament_id))
                    return True, "Torneio finalizado!"

                next_round = current_round + 1
                
                # Busca channel_id de um desafio existente do torneio para usar nos novos desafios
                existing_challenge = cursor.execute("""
                    SELECT channel_id FROM challenges
                    WHERE tournament_id = ? AND channel_id IS NOT NULL AND channel_id != ''
                    LIMIT 1
                """, (tournament_id,)).fetchone()
                channel_id = existing_challenge['channel_id'] if existing_challenge else None
                
                # Lista de vencedores ordenada por match_number
                # Isso garante que o vencedor do Match 1 jogue contra o vencedor do Match 2, etc.
                winner_ids = [w['winner_id'] for w in winners]
                
                match_num = 1
                for i in range(0, len(winner_ids), 2):
                    player1 = winner_ids[i]
                    player2 = winner_ids[i + 1] if i + 1 < len(winner_ids) else None

                    if player2:
                        # Partida normal
                        cursor.execute('''
                            INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, player2_id, status)
                            VALUES (?, ?, ?, ?, ?, 'pending')
                        ''', (tournament_id, next_round, match_num, player1, player2))

                        # Cria desafio automático com channel_id
                        challenge_id = cursor.execute('''
                            INSERT INTO challenges (challenger_id, challenged_id, channel_id, tournament_id, time_control, time_control_mode, status, is_rated)
                            SELECT ?, ?, ?, ?, t.time_control, t.mode, 'pending', t.rated
                            FROM tournaments t WHERE t.id = ?
                        ''', (player1, player2, channel_id or '', tournament_id, tournament_id)).lastrowid

                        cursor.execute('''
                            UPDATE tournament_matches SET challenge_id = ? WHERE tournament_id = ? AND round_number = ? AND match_number = ?
                        ''', (challenge_id, tournament_id, next_round, match_num))
                    else:
                        # Bye - jogador avança automaticamente (caso ímpar de jogadores na rodada)
                        # Isso não deve acontecer em brackets perfeitos de potência de 2, mas é um fallback seguro
                        cursor.execute('''
                            INSERT INTO tournament_matches (tournament_id, round_number, match_number, player1_id, winner_id, status)
                            VALUES (?, ?, ?, ?, ?, 'finished')
                        ''', (tournament_id, next_round, match_num, player1, player1))

                    match_num += 1

            return True, f"Rodada {next_round} iniciada!"
        except Exception as e:
            return False, f"Erro ao avançar rodada: {str(e)}"
    return await asyncio.to_thread(_advance)

async def get_tournament_bracket_data(tournament_id: int):
    """Retorna dados completos do bracket em formato JSON para integração com site/frontend."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        
        # Info do torneio
        cursor.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        tournament = cursor.fetchone()
        if not tournament:
            conn.close()
            return None
            
        # Partidas com detalhes dos jogadores
        cursor.execute("""
            SELECT tm.*, 
                   p1.discord_username as p1_name, p1.avatar_hash as p1_avatar, p1.rating_rapid as p1_rating,
                   p2.discord_username as p2_name, p2.avatar_hash as p2_avatar, p2.rating_rapid as p2_rating,
                   c.game_url
            FROM tournament_matches tm
            LEFT JOIN players p1 ON tm.player1_id = p1.discord_id
            LEFT JOIN players p2 ON tm.player2_id = p2.discord_id
            LEFT JOIN challenges c ON tm.challenge_id = c.id
            WHERE tm.tournament_id = ?
            ORDER BY tm.round_number, tm.match_number
        """, (tournament_id,))
        matches = [dict(m) for m in cursor.fetchall()]
        conn.close()
        
        # Estrutura hierárquica para o frontend
        return {
            "tournament": dict(tournament),
            "matches": matches,
            "generated_at": datetime.datetime.utcnow().isoformat()
        }
    return await asyncio.to_thread(_get)

async def force_tournament_match_winner(tournament_id: int, round_num: int, match_num: int, winner_id: str):
    """Força um vencedor para uma partida de torneio (Admin Tool)."""
    def _force():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Verifica se a partida existe
            cursor.execute("""
                SELECT id, player1_id, player2_id FROM tournament_matches 
                WHERE tournament_id = ? AND round_number = ? AND match_number = ?
            """, (tournament_id, round_num, match_num))
            match = cursor.fetchone()
            if not match:
                return False, "Partida não encontrada."
            
            p1, p2 = match['player1_id'], match['player2_id']
            if str(winner_id) not in [str(p1), str(p2)]:
                return False, "O vencedor informado não faz parte desta partida."

            # Atualiza a partida
            cursor.execute("""
                UPDATE tournament_matches 
                SET winner_id = ?, status = 'finished', finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (winner_id, match['id']))
            
            # Se houver desafio associado, finaliza também para evitar conflitos
            cursor.execute("""
                UPDATE challenges 
                SET status = 'finished', winner_id = ? 
                WHERE tournament_id = ? AND (challenger_id = ? OR challenged_id = ?) AND status != 'finished'
            """, (winner_id, tournament_id, p1, p2))
            
            conn.commit()
            return True, "Vencedor definido com sucesso."
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    return await asyncio.to_thread(_force)

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

async def set_tournament_ranking_channel_id(tournament_id: int, channel_id: str):
    """Define o canal para o ranking do torneio."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE tournaments SET ranking_channel_id = ? WHERE id = ?", (channel_id, tournament_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def set_tournament_ranking_message_id(tournament_id: int, message_id: str):
    """Define a mensagem do ranking do torneio."""
    def _set():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE tournaments SET ranking_message_id = ? WHERE id = ?", (message_id, tournament_id))
        conn.commit()
        conn.close()
    await asyncio.to_thread(_set)

async def update_tournament_standings(tournament_id: int):
    """Atualiza a classificação do torneio baseado nos resultados das partidas."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            with conn:
                # Recalcula pontos baseado nas vitórias
                cursor.execute("""
                    UPDATE tournament_participants
                    SET points = (
                        SELECT COUNT(*)
                        FROM tournament_matches tm
                        WHERE tm.tournament_id = tournament_participants.tournament_id
                        AND tm.winner_id = tournament_participants.player_id
                        AND tm.status = 'finished'
                    )
                    WHERE tournament_id = ?
                """, (tournament_id,))
        finally:
            conn.close()
    await asyncio.to_thread(_update)



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


async def check_swiss_round_completion(tournament_id: int, round_num: int):
    """Verifica se todas as partidas suíças de uma rodada foram finalizadas."""
    def _check():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total, COUNT(CASE WHEN status = 'finished' THEN 1 END) as finished,
                   GROUP_CONCAT(CASE WHEN status != 'finished' THEN id || ':' || status ELSE NULL END) as pending_info
            FROM swiss_pairings WHERE tournament_id = ? AND round_number = ? 
            AND player1_id IS NOT NULL

        """, (tournament_id, round_num))
        progress = cursor.fetchone()
        conn.close()
        result = progress['total'] == progress['finished'] and progress['total'] > 0
        logger.info(f"DEBUG: Torneio {tournament_id}, Rodada {round_num}: total={progress['total']}, finished={progress['finished']}, pending={progress['pending_info']}, resultado={result}")
        return result
    return await asyncio.to_thread(_check)


async def get_swiss_pairing_by_challenge(challenge_id: int):
    """Obtém um pairing suíço pelo challenge_id."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM swiss_pairings
            WHERE challenge_id = ?
        ''', (challenge_id,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None

    return await asyncio.to_thread(_get)


async def get_swiss_pairing_by_game_url(game_url: str):
    """Busca um pairing suíço por URL do jogo."""
    if not game_url:
        return None

    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM swiss_pairings
            WHERE game_url = ?
        ''', (game_url,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    return await asyncio.to_thread(_get)


async def finish_swiss_pairing(tournament_id: int, pairing_id: int, winner_id=None, challenge_id: int = None):
    """Marca um pairing suíço como finalizado e atualiza standings."""
    def _finish():
        try:
            from swiss_tournament import SwissTournament

            conn = get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE swiss_pairings
                SET status = 'finished', winner_id = ?, challenge_id = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ? AND tournament_id = ?
            ''', (winner_id, challenge_id, pairing_id, tournament_id))

            conn.commit()

            swiss = SwissTournament(tournament_id)
            swiss.update_standings()
            swiss.close()

            conn.close()
            return True
        except Exception as e:
            logger.error(f"Erro ao finalizar pairing Swiss: {e}")
            return False

    return await asyncio.to_thread(_finish)

async def start_swiss_tournament(tournament_id: int):
    """Inicia um torneio Swiss."""
    def _start():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            # Verifica se há participantes suficientes
            cursor.execute("SELECT COUNT(*) as count FROM swiss_participants WHERE tournament_id = ?", (tournament_id,))
            count = cursor.fetchone()['count']
            if count < 2:
                return False, "São necessários pelo menos 2 participantes para iniciar o torneio."

            # Atualiza status do torneio
            cursor.execute("UPDATE swiss_tournaments SET status = 'in_progress', started_at = CURRENT_TIMESTAMP WHERE id = ?", (tournament_id,))
            conn.commit()
            return True, "Torneio iniciado com sucesso!"
        except Exception as e:
            return False, f"Erro ao iniciar torneio: {str(e)}"
        finally:
            conn.close()
    return await asyncio.to_thread(_start)

async def generate_and_save_swiss_round(tournament_id: int, round_number: int):
    """Gera e salva uma rodada do torneio Swiss."""
    def _generate():
        try:
            from swiss_tournament import SwissTournament

            swiss = SwissTournament(tournament_id)
            participants = swiss.get_participants()
            logger.info(f"Tournament {tournament_id} has {len(participants)} participants")
            pairings = swiss.generate_pairings(round_number)
            logger.info(f"Generated {len(pairings)} pairings for round {round_number}")
            swiss.close()

            if not participants:
                return False, "Nenhum participante encontrado no torneio"

            if not pairings:
                logger.info(f"Nenhum pairing possível na rodada {round_number}. Torneio finalizando.")
                return False, f"Nenhum pairing possível - nenhum jogador encontrou oponente que não tenha enfrentado"

            conn = get_conn()
            cursor = conn.cursor()
            try:
                for player1_id, player2_id in pairings:
                    if player2_id is None:
                        cursor.execute('''
                            INSERT INTO swiss_pairings (tournament_id, round_number, player1_id, player2_id, status, winner_id, finished_at)
                            VALUES (?, ?, ?, ?, 'finished', ?, CURRENT_TIMESTAMP)
                        ''', (tournament_id, round_number, player1_id, player2_id, player1_id))
                    else:
                        cursor.execute('''
                            INSERT INTO swiss_pairings (tournament_id, round_number, player1_id, player2_id, status)
                            VALUES (?, ?, ?, ?, 'pending')
                        ''', (tournament_id, round_number, player1_id, player2_id))

                conn.commit()
                conn.close()
                
                swiss = SwissTournament(tournament_id)
                swiss.update_standings()
                swiss.close()
                
                return True, pairings
            finally:
                pass
        except Exception as e:
            return False, str(e)

    return await asyncio.to_thread(_generate)

async def get_swiss_pairings_for_round(tournament_id: int, round_number: int):
    """Busca os pairings de uma rodada específica do torneio Swiss."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sp.*, p1.discord_username as player1_name, p2.discord_username as player2_name
            FROM swiss_pairings sp
            LEFT JOIN players p1 ON sp.player1_id = p1.discord_id
            LEFT JOIN players p2 ON sp.player2_id = p2.discord_id
            WHERE sp.tournament_id = ? AND sp.round_number = ?
            ORDER BY sp.id
        ''', (tournament_id, round_number))
        pairings = cursor.fetchall()
        conn.close()
        return [dict(p) for p in pairings]
    return await asyncio.to_thread(_get)

async def update_swiss_pairing_game_url(pairing_id: int, game_url: str):
    """Atualiza o pairing suíço com a URL do jogo."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE swiss_pairings SET game_url = ? WHERE id = ?
        ''', (game_url, pairing_id))
        conn.commit()
        conn.close()
    return await enqueue_write(_update)


async def get_lichess_username(discord_id: str) -> str:
    """Busca o username do Lichess de um jogador."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('SELECT lichess_username FROM players WHERE discord_id = ?', (discord_id,))
        result = cursor.fetchone()
        conn.close()
        return result['lichess_username'] if result else None
    return await asyncio.to_thread(_get)


async def get_swiss_standings(tournament_id: int):
    """Busca a classificação atual do torneio Swiss."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sp.*, p.discord_username, p.lichess_username
            FROM swiss_participants sp
            JOIN players p ON sp.player_id = p.discord_id
            WHERE sp.tournament_id = ?
            ORDER BY sp.points DESC, sp.tiebreak_score DESC
        ''', (tournament_id,))
        standings = cursor.fetchall()
        conn.close()
        return [dict(s) for s in standings]
    return await asyncio.to_thread(_get)

async def get_swiss_pairing_by_id(pairing_id: int):
    """Busca um pairing suíço específico pelo ID."""
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sp.*, st.name as tournament_name, st.time_control
            FROM swiss_pairings sp
            JOIN swiss_tournaments st ON sp.tournament_id = st.id
            WHERE sp.id = ?
        ''', (pairing_id,))
        pairing = cursor.fetchone()
        conn.close()
        return dict(pairing) if pairing else None
    return await asyncio.to_thread(_get)

async def update_swiss_pairing_challenge(pairing_id: int, challenge_id: int):
    """Atualiza o challenge_id de um pairing suíço."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE swiss_pairings SET challenge_id = ? WHERE id = ?", (challenge_id, pairing_id))
        conn.commit()
        conn.close()

    await enqueue_write(_update)

async def update_swiss_pairing_result(pairing_id: int, winner_id: str, loser_id: str, result: str):
    """Atualiza o resultado de um pairing suíço."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE swiss_pairings SET winner_id = ?, status = ? WHERE id = ?",
            (winner_id if result == 'win' else None, 'finished', pairing_id)
        )
        conn.commit()
        logger.info(f"✅ Pairing {pairing_id} marcado como finished. Winner: {winner_id}, Result: {result}")
        conn.close()

    await enqueue_write(_update)

async def update_swiss_standings(tournament_id: int, player1_id: str, player2_id: str, result: str, reason: str = 'unknown'):
    """Atualiza a classificação do torneio suíço com o resultado de uma partida.
    
    Args:
        tournament_id: ID do torneio
        player1_id: ID do jogador 1
        player2_id: ID do jogador 2 (ou ID do perdedor se result='win')
        result: 'draw' ou 'win'
        reason: Razão da vitória (resign, checkmate, etc)
    """
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        
        try:
            if result == 'draw':
                cursor.execute("""
                    UPDATE swiss_participants
                    SET points = points + 0.5, draws = draws + 1
                    WHERE tournament_id = ? AND player_id IN (?, ?)
                """, (tournament_id, player1_id, player2_id))
            elif result == 'win':
                winner_id = player1_id
                loser_id = player2_id
                
                cursor.execute("""
                    UPDATE swiss_participants
                    SET points = points + 1.0, wins = wins + 1
                    WHERE tournament_id = ? AND player_id = ?
                """, (tournament_id, winner_id))
                cursor.execute("""
                    UPDATE swiss_participants
                    SET losses = losses + 1
                    WHERE tournament_id = ? AND player_id = ?
                """, (tournament_id, loser_id))
            
            conn.commit()
        except Exception as e:
            logger.error(f"Erro ao atualizar standings: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    await enqueue_write(_update)

async def apply_draw_ratings(player1_id: str, player2_id: str, mode: str):
    """Aplica mudanças de rating ELO para empate entre dois jogadores."""
    def _apply():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(f"SELECT rating_{mode} FROM players WHERE discord_id = ?", (player1_id,))
            player1_rating_row = cursor.fetchone()
            cursor.execute(f"SELECT rating_{mode} FROM players WHERE discord_id = ?", (player2_id,))
            player2_rating_row = cursor.fetchone()

            if not player1_rating_row or not player2_rating_row:
                return None

            player1_rating = player1_rating_row[0] or 1200
            player2_rating = player2_rating_row[0] or 1200

            player1_expected = 1 / (1 + 10 ** ((player2_rating - player1_rating) / 400))
            player2_expected = 1 / (1 + 10 ** ((player1_rating - player2_rating) / 400))

            k_factor = 32

            player1_change = round(k_factor * (0.5 - player1_expected))
            player2_change = round(k_factor * (0.5 - player2_expected))

            new_player1_rating = player1_rating + player1_change
            new_player2_rating = player2_rating + player2_change

            cursor.execute(f"UPDATE players SET rating_{mode} = ? WHERE discord_id = ?", (new_player1_rating, player1_id))
            cursor.execute(f"UPDATE players SET rating_{mode} = ? WHERE discord_id = ?", (new_player2_rating, player2_id))

            conn.commit()

            return {
                'player1': {'old': player1_rating, 'new': new_player1_rating, 'change': player1_change},
                'player2': {'old': player2_rating, 'new': new_player2_rating, 'change': player2_change}
            }
        except Exception as e:
            logger.error(f"Erro ao aplicar ratings de empate: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    return await enqueue_write(_apply)

async def finish_swiss_tournament(tournament_id: int):
    """Marca um torneio suíço como finalizado."""
    def _finish():
        conn = get_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE swiss_tournaments SET status = 'finished', finished_at = CURRENT_TIMESTAMP WHERE id = ?",
                (tournament_id,)
            )
            conn.commit()
            logger.info(f"Torneio suíço {tournament_id} marcado como finalizado")
            return True
        except Exception as e:
            logger.error(f"Erro ao finalizar torneio {tournament_id}: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    return await asyncio.to_thread(_finish)

# ==============================================================================
# --- FUNÇÕES PARA HISTÓRICO DE PARTIDAS E ESTATÍSTICAS ---
# ==============================================================================

async def save_game_history(player1_id: str, player2_id: str, player1_name: str, player2_name: str,
                            winner_id: str, result: str, mode: str, time_control: str = None,
                            game_url: str = None, p1_rating_before: int = None, p2_rating_before: int = None,
                            p1_rating_after: int = None, p2_rating_after: int = None):
    """Salva um registro de partida no histórico de jogos."""
    def _save():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO game_history (player1_id, player2_id, player1_name, player2_name, winner_id, result,
                                      mode, time_control, game_url, player1_rating_before, player2_rating_before,
                                      player1_rating_after, player2_rating_after)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (player1_id, player2_id, player1_name, player2_name, winner_id, result, mode,
              time_control, game_url, p1_rating_before, p2_rating_before, p1_rating_after, p2_rating_after))
        conn.commit()
        conn.close()
    
    await enqueue_write(_save)

async def get_player_game_history(discord_id: str, limit: int = 10):
    """Retorna as últimas partidas de um jogador."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM game_history
            WHERE player1_id = ? OR player2_id = ?
            ORDER BY played_at DESC
            LIMIT ?
        ''', (discord_id, discord_id, limit))
        games = cursor.fetchall()
        conn.close()
        return [dict(game) for game in games]
    
    return await asyncio.to_thread(_fetch)

async def save_rating_snapshot(discord_id: str, mode: str, rating: int):
    """Salva um snapshot do rating para histórico de evolução."""
    def _save():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO rating_history (player_id, mode, rating)
            VALUES (?, ?, ?)
        ''', (discord_id, mode, rating))
        conn.commit()
        conn.close()
    
    await enqueue_write(_save)

async def get_rating_history(discord_id: str, mode: str, limit: int = 30):
    """Retorna o histórico de ratings de um jogador para um modo específico."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM rating_history
            WHERE player_id = ? AND mode = ?
            ORDER BY recorded_at ASC
            LIMIT ?
        ''', (discord_id, mode, limit))
        history = cursor.fetchall()
        conn.close()
        return [dict(record) for record in history]
    
    return await asyncio.to_thread(_fetch)

async def unlock_achievement(discord_id: str, achievement_type: str, achievement_name: str, description: str = None):
    """Desbloqueia um achievement para um jogador."""
    def _unlock():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
            VALUES (?, ?, ?, ?)
        ''', (discord_id, achievement_type, achievement_name, description))
        conn.commit()
        conn.close()
    
    await enqueue_write(_unlock)

async def get_player_achievements(discord_id: str):
    """Retorna todos os achievements de um jogador."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT achievement_type, achievement_name, description, unlocked_at
            FROM achievements
            WHERE player_id = ?
            ORDER BY unlocked_at DESC
        ''', (discord_id,))
        achievements = cursor.fetchall()
        conn.close()
        return [dict(ach) for ach in achievements]
    
    return await asyncio.to_thread(_fetch)

async def update_head_to_head(player1_id: str, player2_id: str, result: str):
    """Atualiza o record head-to-head entre dois jogadores. result: 'win', 'loss' ou 'draw'."""
    def _update():
        conn = get_conn()
        cursor = conn.cursor()
        
        # Garantir que player1_id < player2_id para manter apenas um registro
        if player1_id > player2_id:
            player1_id, player2_id = player2_id, player1_id
            if result == 'win':
                result = 'loss'
            elif result == 'loss':
                result = 'win'
        
        cursor.execute('''
            SELECT * FROM head_to_head
            WHERE player1_id = ? AND player2_id = ?
        ''', (player1_id, player2_id))
        
        record = cursor.fetchone()
        
        if record:
            if result == 'win':
                cursor.execute('''
                    UPDATE head_to_head
                    SET player1_wins = player1_wins + 1, last_game_at = CURRENT_TIMESTAMP
                    WHERE player1_id = ? AND player2_id = ?
                ''', (player1_id, player2_id))
            elif result == 'loss':
                cursor.execute('''
                    UPDATE head_to_head
                    SET player2_wins = player2_wins + 1, last_game_at = CURRENT_TIMESTAMP
                    WHERE player1_id = ? AND player2_id = ?
                ''', (player1_id, player2_id))
            elif result == 'draw':
                cursor.execute('''
                    UPDATE head_to_head
                    SET draws = draws + 1, last_game_at = CURRENT_TIMESTAMP
                    WHERE player1_id = ? AND player2_id = ?
                ''', (player1_id, player2_id))
        else:
            if result == 'win':
                cursor.execute('''
                    INSERT INTO head_to_head (player1_id, player2_id, player1_wins, player2_wins, draws)
                    VALUES (?, ?, 1, 0, 0)
                ''', (player1_id, player2_id))
            elif result == 'loss':
                cursor.execute('''
                    INSERT INTO head_to_head (player1_id, player2_id, player1_wins, player2_wins, draws)
                    VALUES (?, ?, 0, 1, 0)
                ''', (player1_id, player2_id))
            elif result == 'draw':
                cursor.execute('''
                    INSERT INTO head_to_head (player1_id, player2_id, player1_wins, player2_wins, draws)
                    VALUES (?, ?, 0, 0, 1)
                ''', (player1_id, player2_id))
        
        conn.commit()
        conn.close()
    
    await enqueue_write(_update)

async def get_head_to_head(player1_id: str, player2_id: str):
    """Retorna o record head-to-head entre dois jogadores."""
    def _fetch():
        conn = get_conn()
        cursor = conn.cursor()
        
        # Garantir que player1_id < player2_id para manter apenas um registro
        if player1_id > player2_id:
            player1_id, player2_id = player2_id, player1_id
        
        cursor.execute('''
            SELECT * FROM head_to_head
            WHERE player1_id = ? AND player2_id = ?
        ''', (player1_id, player2_id))
        
        record = cursor.fetchone()
        conn.close()
        return dict(record) if record else None
    
    return await asyncio.to_thread(_fetch)

async def check_and_unlock_achievements(player_id: str, mode: str, result: str, opponent_id: str = None):
    """Verifica e desbloqueia achievements baseado no resultado de uma partida."""
    achievements_unlocked = []
    
    def _check_achievements():
        conn = get_conn()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT * FROM players WHERE discord_id = ?", (player_id,))
            player = cursor.fetchone()
            if not player:
                return []
            
            player_dict = dict(player)
            unlocked = []
            
            # Primeira Vitória
            if result == 'win':
                cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                             (player_id, 'first_win'))
                if cursor.fetchone()['count'] == 0:
                    cursor.execute('''
                        INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                        VALUES (?, ?, ?, ?)
                    ''', (player_id, 'first_win', '🎯 Primeira Vitória', 'Vença sua primeira partida'))
                    conn.commit()
                    unlocked.append('first_win')
                    logger.info(f"🏆 Achievement 'Primeira Vitória' desbloqueado para {player_id}")
            
            # Win Streak 3 e 5
            if result == 'win':
                current_wins = sum([player_dict.get(f'wins_{m}', 0) or 0 for m in ['bullet', 'blitz', 'rapid', 'classic']])
                
                if current_wins >= 5:
                    cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                                 (player_id, 'win_streak_5'))
                    if cursor.fetchone()['count'] == 0:
                        cursor.execute('''
                            INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                            VALUES (?, ?, ?, ?)
                        ''', (player_id, 'win_streak_5', '🌟 Win Streak 5', 'Vença 5 partidas consecutivas'))
                        conn.commit()
                        unlocked.append('win_streak_5')
                        logger.info(f"🏆 Achievement 'Win Streak 5' desbloqueado para {player_id}")
                
                elif current_wins >= 3:
                    cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                                 (player_id, 'win_streak_3'))
                    if cursor.fetchone()['count'] == 0:
                        cursor.execute('''
                            INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                            VALUES (?, ?, ?, ?)
                        ''', (player_id, 'win_streak_3', '🔥 Win Streak 3', 'Vença 3 partidas consecutivas'))
                        conn.commit()
                        unlocked.append('win_streak_3')
                        logger.info(f"🏆 Achievement 'Win Streak 3' desbloqueado para {player_id}")
            
            # Rating Achievements
            rating = player_dict.get(f'rating_{mode}', 1200) or 1200
            
            if rating >= 1800:
                cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                             (player_id, 'rating_1800'))
                if cursor.fetchone()['count'] == 0:
                    cursor.execute('''
                        INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                        VALUES (?, ?, ?, ?)
                    ''', (player_id, 'rating_1800', '👑 Rating 1800+', 'Atinja rating de 1800 ou mais'))
                    conn.commit()
                    unlocked.append('rating_1800')
                    logger.info(f"🏆 Achievement 'Rating 1800+' desbloqueado para {player_id}")
            
            elif rating >= 1500:
                cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                             (player_id, 'rating_1500'))
                if cursor.fetchone()['count'] == 0:
                    cursor.execute('''
                        INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                        VALUES (?, ?, ?, ?)
                    ''', (player_id, 'rating_1500', '⭐ Rating 1500+', 'Atinja rating de 1500 ou mais'))
                    conn.commit()
                    unlocked.append('rating_1500')
                    logger.info(f"🏆 Achievement 'Rating 1500+' desbloqueado para {player_id}")
            
            # Head-to-head achievements
            if opponent_id:
                p1 = min(player_id, opponent_id)
                p2 = max(player_id, opponent_id)
                cursor.execute('''
                    SELECT (player1_wins + player2_wins + draws) as total_games
                    FROM head_to_head
                    WHERE player1_id = ? AND player2_id = ?
                ''', (p1, p2))
                h2h_record = cursor.fetchone()
                
                if h2h_record and h2h_record['total_games'] >= 5:
                    cursor.execute("SELECT COUNT(*) as count FROM achievements WHERE player_id = ? AND achievement_type = ?", 
                                 (player_id, 'head_to_head_5'))
                    if cursor.fetchone()['count'] == 0:
                        cursor.execute('''
                            INSERT OR IGNORE INTO achievements (player_id, achievement_type, achievement_name, description)
                            VALUES (?, ?, ?, ?)
                        ''', (player_id, 'head_to_head_5', '🎪 Rival', 'Jogue 5 partidas contra o mesmo adversário'))
                        conn.commit()
                        unlocked.append('head_to_head_5')
                        logger.info(f"🏆 Achievement 'Rival' desbloqueado para {player_id}")
            
            return unlocked
        
        except Exception as e:
            logger.error(f"Erro ao verificar achievements para {player_id}: {e}")
            return []


async def check_pairing_notified(pairing_id: int) -> bool:
    """Verifica se um pairing já foi notificado para evitar duplicatas."""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        cursor.execute("SELECT notified FROM swiss_pairings WHERE id = ?", (pairing_id,))
        result = cursor.fetchone()
        
        if result:
            return result['notified'] == 1
        
        return False
    except Exception as e:
        logger.error(f"Erro ao verificar se pairing foi notificado: {e}")
        return False


async def mark_pairing_notified(pairing_id: int) -> bool:
    """Marca um pairing como notificado."""
    try:
        conn = get_conn()
        cursor = conn.cursor()
        
        cursor.execute("UPDATE swiss_pairings SET notified = 1 WHERE id = ?", (pairing_id,))
        conn.commit()
        
        return True
    except Exception as e:
        logger.error(f"Erro ao marcar pairing como notificado: {e}")
        return False
# ==============================================================================
# --- FUNÇÕES PARA API (Retorno de dados formatados) ---
# ==============================================================================

async def get_ranking_by_mode_for_api(mode: str):
    """Retorna a classificação formatada para o API do site.
    
    Retorna um dict com:
    - jogadores: Lista de jogadores com avatar_hash, id_discord, etc.
    - ultimo_update: Timestamp do último update
    """
    def _get():
        conn = get_conn()
        cursor = conn.cursor()
        
        # Busca jogadores ordenados por rating da modalidade
        cursor.execute(f'''
            SELECT 
                discord_id,
                discord_username as nome,
                avatar_hash,
                rating_{mode} as rating,
                wins_{mode} as vitorias,
                losses_{mode} as derrotas,
                draws_{mode} as empates,
                (wins_{mode} + losses_{mode} + draws_{mode}) as partidas_jogadas
            FROM players
            WHERE rating_{mode} > 1000
            ORDER BY rating_{mode} DESC
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        # Converter para lista de dicts
        jogadores = []
        for row in rows:
            player = dict(row)
            jogadores.append({
                'id_discord': player['discord_id'],
                'nome': player['nome'],
                'avatar_hash': player['avatar_hash'],
                'rating': player['rating'] or 1200,
                'vitorias': player['vitorias'] or 0,
                'derrotas': player['derrotas'] or 0,
                'empates': player['empates'] or 0,
                'partidas_jogadas': player['partidas_jogadas'] or 0
            })
        
        return {
            'jogadores': jogadores,
            'ultimo_update': datetime.datetime.now().isoformat()
        }
    
    return await asyncio.to_thread(_get)