import aiohttp
import asyncio
import logging
import os
from typing import Optional, Dict
from urllib.parse import urlencode
import aiohttp

LICHESS_API_BASE = "https://lichess.org"

logger = logging.getLogger(__name__)

_last_create_game_error: Optional[str] = None

# Lista para rastrear sessões ativas (para cleanup)
_active_sessions = set()

def get_last_create_game_error() -> Optional[str]:
    """Retorna a última mensagem de erro ao tentar criar uma partida."""
    return _last_create_game_error

async def cleanup_sessions():
    """Fecha todas as sessões HTTP ativas para evitar vazamentos."""
    logger.info(f"Limpando {_active_sessions.__len__()} sessões HTTP ativas...")
    for session in _active_sessions.copy():
        try:
            if not session.closed:
                await session.close()
                logger.debug("Sessão HTTP fechada com sucesso.")
        except Exception as e:
            logger.warning(f"Erro ao fechar sessão HTTP: {e}")
        finally:
            _active_sessions.discard(session)
    logger.info("Limpeza de sessões HTTP concluída.")

class ManagedClientSession:
    """Context manager para sessões HTTP que garante limpeza adequada."""
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        _active_sessions.add(self.session)
        return self.session
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and not self.session.closed:
            await self.session.close()
        if self.session in _active_sessions:
            _active_sessions.discard(self.session)

async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[Dict]:
    try:
        async with session.get(url, headers={"Accept": "application/json"}, timeout=20) as resp:
            if resp.status == 200:
                return await resp.json()
            elif resp.status == 404:
                # Jogo não encontrado - isso é normal para jogos antigos/deletados
                logger.debug(f"Jogo não encontrado na URL {url}")
                return None
            else:
                logger.warning(f"Erro ao buscar JSON da URL {url}. Status: {resp.status}, Resposta: {await resp.text()}")
                return None
    except Exception as e:
        logger.error(f"Exceção ao buscar JSON da URL {url}: {e}")
        return None

async def get_game_outcome(game_url: str) -> Optional[Dict]:
    """
    Given a lichess game URL, query its status and derive outcome information.
    Returns a dict or None if the game is not found or an error occurs.
      {
        'finished': bool,
        'is_draw': bool,
        'winner_color': 'white' | 'black' | None,
        'winner_username': str | None,
        'reason': str,  # resign | checkmate | timeout | draw | aborted | unknown
        'pgn': str | None,
        'players': {
            'white': {'username': str | None, 'rating': int | None},
            'black': {'username': str | None, 'rating': int | None}
        },
        'game_stats': {
            'moves': int | None,
            'time_control': str | None,
            'opening': str | None,
            'created_at': str | None,
            'last_move_at': str | None
        }
      }
    Notes:
    - This uses the public /api/game endpoint if possible. If not available, we fallback best-effort.
    - If PGN is not available via JSON, we leave it None.
    """
    # Extract game id from URL like https://lichess.org/<gameId> or .../embed/...
    game_id = game_url.rstrip('/').split('/')[-1]
    json_url = f"{LICHESS_API_BASE}/game/export/{game_id}?format=json&evals=1&opening=true"

    async with ManagedClientSession() as session:
        try:
            data = await _fetch_json(session, json_url)
            if not data:
                logger.debug(f"Não foi possível obter dados da partida {game_id}")
                return None
        except Exception as e:
            logger.debug(f"Erro ao buscar resultado da partida {game_id}: {e}")
            return None

        status = data.get('status')  # e.g., "mate", "resign", "stalemate", "draw", "timeout", "outoftime", "aborted", "started", "created", "unknownFinish"
        winner_color = data.get('winner')  # "white" | "black" | None
        white = data.get('players', {}).get('white', {})
        black = data.get('players', {}).get('black', {})
        white_user = (white.get('user') or {}).get('name') if isinstance(white.get('user'), dict) else white.get('user')
        black_user = (black.get('user') or {}).get('name') if isinstance(black.get('user'), dict) else black.get('user')
        white_rating = white.get('rating')
        black_rating = black.get('rating')
        pgn = data.get('pgn')

        # Extract game statistics
        moves = data.get('turns')  # Number of half-moves (full moves = turns/2)
        clock = data.get('clock')
        time_control = f"{clock['initial']//60}+{clock['increment']}" if clock else None
        opening = data.get('opening', {}).get('name') if data.get('opening') else None
        created_at = data.get('createdAt')
        last_move_at = data.get('lastMoveAt')

        # Determine finished / draw / reason
        finished = status not in (None, 'started', 'created')
        is_draw = status in ('stalemate', 'draw', 'repetition', 'insufficient', '50moves', 'agreed') or (winner_color is None and finished and status not in ('aborted',))

        # Normalize reason
        reason_map = {
            'mate': 'checkmate',
            'resign': 'resign',
            'stalemate': 'draw',
            'draw': 'draw',
            'repetition': 'draw',
            'insufficient': 'draw',
            '50moves': 'draw',
            'agreed': 'draw',
            'timeout': 'timeout',
            'outoftime': 'timeout',
            'aborted': 'aborted',
        }
        reason = reason_map.get(status, 'unknown')

        # Final evaluation logic (keep existing)
        final_evaluation = None
        # Assuming 'analysis' field might be present with evals=true
        if 'analysis' in data and data['analysis']:
            last_eval_entry = data['analysis'][-1] if isinstance(data['analysis'], list) and data['analysis'] else None
            if last_eval_entry and 'eval' in last_eval_entry:
                final_evaluation = last_eval_entry['eval']
            elif last_eval_entry and 'mate' in last_eval_entry:
                final_evaluation = f"Mate in {last_eval_entry['mate']}"
        elif 'moves' in data: # Try to get evaluation from the last move if available
            last_move = data['moves'][-1] if isinstance(data['moves'], list) and data['moves'] else None
            if isinstance(last_move, dict) and 'eval' in last_move:
                final_evaluation = last_move['eval']
            elif isinstance(last_move, dict) and 'mate' in last_move:
                final_evaluation = f"Mate in {last_move['mate']}"


        # Consolidate existing player data
        white_player_data = {
            'username': white_user,
            'rating': white_rating
        }
        black_player_data = {
            'username': black_user,
            'rating': black_rating
        }


        return {
            'finished': finished,
            'is_draw': is_draw,
            'winner_color': winner_color if not is_draw else None,
            'winner_username': white_user if winner_color == 'white' else (black_user if winner_color == 'black' else None),
            'reason': reason,
            'pgn': pgn,
            'moves': data.get('moves', []),
            'players': {
                'white': white_player_data,
                'black': black_player_data,
            },
            'game_stats': {
                'moves': moves,
                'time_control': time_control,
                'opening': opening,
                'created_at': created_at,
                'last_move_at': last_move_at
            },
            'analysis': {
                'final_evaluation': final_evaluation
            }
        }

async def get_game_pgn(game_id: str) -> Optional[str]:
    """
    Fetches the PGN for a given Lichess game ID.
    """
    url = f"{LICHESS_API_BASE}/game/export/{game_id}"
    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/x-chess-pgn"}, timeout=20) as resp:
                if resp.status == 200:
                    return await resp.text()
                else:
                    logger.warning(f"Erro ao buscar PGN do jogo {game_id}. Status: {resp.status}, Resposta: {await resp.text()}")
                    return None
        except Exception as e:
            logger.error(f"Exceção ao buscar PGN do jogo {game_id}: {e}")
            return None


async def get_cloud_eval(fen: str) -> Optional[Dict]:
    """
    Fetches the cloud evaluation for a given FEN from Lichess.
    Returns a dict with 'cp', 'mate', 'pv' or None if not found.
    """
    url = f"{LICHESS_API_BASE}/api/cloud-eval/{fen}"
    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        'cp': data.get('cp'),
                        'mate': data.get('mate'),
                        'pv': data.get('pv', [])
                    }
                else:
                    logger.debug(f"Cloud eval not found for FEN {fen}. Status: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Exceção ao buscar cloud eval para FEN {fen}: {e}")
            return None


async def create_swiss_game(time_control: str, rated: bool = True) -> Optional[str]:
    """
    Cria um desafio aberto para torneios suíços no Lichess.

    Args:
        time_control: String no formato "minutos+incremento" (ex: "10+0", "5+3")
        rated: Se a partida deve contar para o rating

    Returns:
        URL da partida no Lichess ou None em caso de erro
    """
    logger.info(f"create_swiss_game chamado com time_control={time_control}, rated={rated}")
    # Para torneios suíços, vamos usar a função existente que funciona
    result = await create_lichess_game(time_control, rated)
    logger.info(f"create_swiss_game retornou: {result}")
    return result


async def create_lichess_game(time_control: str, rated: bool = True) -> Optional[str]:
    """
    Cria um desafio aberto no Lichess e retorna a URL da partida.
    
    Args:
        time_control: String no formato "minutos+incremento" (ex: "10+0", "5+3")
        rated: Se a partida deve contar para o rating
        
    Returns:
        URL da partida no Lichess ou None em caso de erro
    """
    global _last_create_game_error
    _last_create_game_error = None

    token = os.environ.get('LICHESS_TOKEN')

    if not token:
        _last_create_game_error = "Token do Lichess não configurado. Configure a variável LICHESS_TOKEN."
        logger.error(_last_create_game_error)
        return None
    
    # Parse time_control (formato: "10+0" ou "5+3")
    try:
        parts = time_control.split('+')
        minutes = int(parts[0])
        increment = int(parts[1]) if len(parts) > 1 else 0
        clock_limit = minutes * 60  # converter minutos para segundos
    except (ValueError, IndexError):
        # Formato inválido, usar padrão
        clock_limit = 600  # 10 minutos
        increment = 0
        logger.warning("Controle de tempo inválido informado. Usando padrão 10+0.")
    
    url = f"{LICHESS_API_BASE}/api/challenge/open"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    
    rated_value = 'true' if bool(rated) else 'false'

    # Preparar dados do formulário
    data = {
        "rated": rated_value,
        "clock.limit": str(clock_limit),
        "clock.increment": str(increment),
        "variant": "standard",
        "color": "random",
        "acceptanceType": "registered"
    }
    
    async with ManagedClientSession() as session:
        try:
            async with session.post(url, headers=headers, data=urlencode(data), timeout=20) as resp:
                if 200 <= resp.status < 300:
                    try:
                        result = await resp.json()
                    except:
                        logger.error("Falha ao interpretar resposta da API do Lichess: status=%s", resp.status)
                        return None
                    
                    # A resposta da API do Lichess geralmente retorna um objeto com 'challenge'
                    if isinstance(result, dict):
                        # Verificar se há um objeto 'challenge' aninhado
                        challenge = result.get('challenge')
                        if challenge:
                            if isinstance(challenge, dict):
                                # Pode ter 'url' diretamente
                                challenge_url = challenge.get('url')
                                if challenge_url:
                                    _last_create_game_error = None
                                    return challenge_url
                                # Ou pode ter 'id' e precisamos construir a URL
                                challenge_id = challenge.get('id')
                                if challenge_id:
                                    _last_create_game_error = None
                                    return f"{LICHESS_API_BASE}/{challenge_id}"
                        
                        # Verificar se há 'url' no nível raiz
                        if 'url' in result:
                            _last_create_game_error = None
                            return result['url']
                        
                        # Verificar se há 'id' no nível raiz
                        if 'id' in result:
                            _last_create_game_error = None
                            return f"{LICHESS_API_BASE}/{result['id']}"
                        
                        # Verificar se há 'challenge' como string (ID)
                        challenge_id = result.get('challenge')
                        if isinstance(challenge_id, str):
                            _last_create_game_error = None
                            return f"{LICHESS_API_BASE}/{challenge_id}"

                        # Algumas respostas podem trazer 'challenge' como lista (em casos raros)
                        if isinstance(challenge, list) and challenge:
                            first_challenge = challenge[0]
                            if isinstance(first_challenge, dict):
                                challenge_url = first_challenge.get('url')
                                if challenge_url:
                                    _last_create_game_error = None
                                    return challenge_url
                                challenge_id = first_challenge.get('id')
                                if challenge_id:
                                    _last_create_game_error = None
                                    return f"{LICHESS_API_BASE}/{challenge_id}"

                    _last_create_game_error = "Resposta inesperada ao criar desafio no Lichess."
                    logger.error("Resposta inesperada ao criar desafio no Lichess: %s", result)
                    return None

                # Se status não for sucesso (>=200,<300), tentar obter detalhes do erro
                error_text = await resp.text()
                if resp.status == 401:
                    _last_create_game_error = "Token do Lichess inválido ou sem permissão para criar desafios."
                    logger.error("Token do Lichess inválido ou ausente ao criar desafio. Resposta: %s", error_text)
                elif resp.status == 400:
                    _last_create_game_error = f"Parâmetros inválidos ao criar desafio no Lichess. Detalhes: {error_text}"
                    logger.error("Requisição inválida ao criar desafio no Lichess. Dados: %s | Resposta: %s", data, error_text)
                else:
                    _last_create_game_error = "Falha inesperada ao criar desafio no Lichess."
                    logger.error("Falha ao criar desafio no Lichess. Status: %s | Resposta: %s", resp.status, error_text)
                return None
        except aiohttp.ClientError as e:
            _last_create_game_error = "Falha de conexão com a API do Lichess."
            logger.error("Erro de conexão ao comunicar com a API do Lichess: %s", e)
            return None
        except Exception as e:
            _last_create_game_error = "Erro inesperado ao criar desafio no Lichess."
            logger.error("Erro inesperado ao criar desafio no Lichess: %s", e)
            return None

async def verify_user_exists(username: str) -> bool:
    """Verifica se um usuário existe no Lichess (case-insensitive)."""
    if not username:
        return False
    url = f"{LICHESS_API_BASE}/api/user/{username}"
    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=15) as resp:
                return resp.status == 200
        except Exception:
            return False

async def create_lichess_tournament(
    name: str,
    description: str = "",
    clock_time: int = 10,
    clock_increment: int = 0,
    minutes: int = 60,
    variant: str = "standard",
    rated: bool = True,
    position: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    password: str = "",
    team_id: str = "",
    min_rating: int = None,
    max_rating: int = None,
    nb_rated_games: int = None,
    berserkable: bool = True,
    streakable: bool = True,
    manual_pairings: bool = False,
    chat_for: int = 0,
    allow_list: str = "",
    start_date: str = None
) -> Optional[str]:
    """
    Cria um torneio no Lichess com todos os parâmetros disponíveis e retorna o ID do torneio.

    Args:
        name: Nome do torneio (obrigatório)
        description: Descrição do torneio
        clock_time: Tempo inicial em minutos
        clock_increment: Incremento em segundos
        minutes: Duração do torneio em minutos
        variant: Variante do jogo ("standard", "chess960", etc.)
        rated: Se o torneio vale rating
        position: Posição inicial em FEN
        password: Senha para entrar no torneio
        team_id: ID do time (restrição de participação)
        min_rating: Rating mínimo para participar
        max_rating: Rating máximo para participar
        nb_rated_games: Número mínimo de jogos rated
        berserkable: Permitir berserk
        streakable: Permitir bônus de streak
        manual_pairings: Pareamento manual
        chat_for: Quem pode conversar (0=ninguém, 10=membros, 20=todos)
        allow_list: Lista de usuários permitidos (separados por vírgula)
        start_date: Data de início (formato ISO, ex: "2024-01-01T12:00:00Z")

    Returns:
        ID do torneio no Lichess ou None em caso de erro
    """
    global _last_create_game_error
    _last_create_game_error = None

    token = os.environ.get('LICHESS_TOKEN')

    if not token:
        _last_create_game_error = "Token do Lichess não configurado. Configure a variável LICHESS_TOKEN."
        logger.error(_last_create_game_error)
        return None

    url = f"{LICHESS_API_BASE}/api/tournament"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    # Preparar dados com todos os parâmetros
    data = {
        "name": name,
        "description": description,
        "clockTime": str(clock_time),
        "clockIncrement": str(clock_increment),
        "minutes": str(minutes),
        "variant": variant,
        "rated": "true" if rated else "false",
        "position": position,
        "password": password,
        "conditions.teamMember.teamId": team_id,
        "conditions.minRating.rating": str(min_rating) if min_rating is not None else "",
        "conditions.maxRating.rating": str(max_rating) if max_rating is not None else "",
        "conditions.nbRatedGame.nb": str(nb_rated_games) if nb_rated_games is not None else "",
        "berserkable": "true" if berserkable else "false",
        "streakable": "true" if streakable else "false",
        "manualPairings": "true" if manual_pairings else "false",
        "chatFor": str(chat_for),
        "allowList": allow_list
    }

    if start_date:
        data["startDate"] = start_date

    # Implementar retry com exponential backoff para lidar com rate limiting
    max_retries = 5
    base_delay = 2  # segundos

    for attempt in range(max_retries):
        async with ManagedClientSession() as session:
            try:
                async with session.post(url, headers=headers, data=data, timeout=30) as resp:
                    if 200 <= resp.status < 300:
                        try:
                            result = await resp.json()
                            tournament_id = result.get('id')
                            if tournament_id:
                                _last_create_game_error = None
                                return tournament_id
                            else:
                                _last_create_game_error = "Resposta da API não contém ID do torneio."
                                logger.error("Resposta da API do Lichess não contém ID: %s", result)
                                return None
                        except Exception as e:
                            _last_create_game_error = "Falha ao interpretar resposta da API."
                            logger.error("Erro ao interpretar resposta: %s", e)
                            return None
                    elif resp.status == 429:
                        # Rate limiting - implementar backoff exponencial
                        delay = base_delay * (2 ** attempt)  # 2, 4, 8, 16, 32 segundos
                        logger.warning(f"Rate limiting detectado (429). Tentativa {attempt + 1}/{max_retries}. Aguardando {delay}s antes de tentar novamente.")
                        if attempt < max_retries - 1:  # Não aguardar na última tentativa
                            await asyncio.sleep(delay)
                            continue
                        else:
                            error_text = await resp.text()
                            _last_create_game_error = f"Rate limiting persistente após {max_retries} tentativas: {error_text}"
                            logger.error("Rate limiting persistente: %s", error_text)
                            return None
                    else:
                        error_text = await resp.text()
                        if resp.status == 401:
                            _last_create_game_error = "Token do Lichess inválido."
                        elif resp.status == 400:
                            _last_create_game_error = f"Parâmetros inválidos: {error_text}"
                        else:
                            _last_create_game_error = f"Erro na API do Lichess: {resp.status}"
                        logger.error("Erro ao criar torneio: %s", error_text)
                        return None
            except Exception as e:
                _last_create_game_error = f"Erro de conexão: {str(e)}"
                logger.error("Erro ao criar torneio no Lichess: %s", e)
                return None

    # Se chegou aqui, todas as tentativas falharam
    _last_create_game_error = f"Falha após {max_retries} tentativas devido a rate limiting."
    return None

async def get_lichess_tournament_results(tournament_id: str) -> Optional[Dict]:
    """
    Busca os resultados de um torneio no Lichess.
    
    Args:
        tournament_id: ID do torneio no Lichess
        
    Returns:
        Dict com informações do torneio ou None
    """
    url = f"{LICHESS_API_BASE}/api/tournament/{tournament_id}/results"
    
    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=20) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    return results
                else:
                    logger.warning(f"Erro ao buscar resultados do torneio {tournament_id}: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Erro ao buscar resultados do torneio {tournament_id}: {e}")
            return None

async def get_lichess_tournament_info(tournament_id: str) -> Optional[Dict]:
    """
    Busca informações de um torneio no Lichess.

    Args:
        tournament_id: ID do torneio no Lichess

    Returns:
        Dict com informações do torneio ou None
    """
    url = f"{LICHESS_API_BASE}/api/tournament/{tournament_id}"

    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=20) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    return info
                else:
                    logger.warning(f"Erro ao buscar info do torneio {tournament_id}: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Erro ao buscar info do torneio {tournament_id}: {e}")
            return None

async def create_lichess_swiss_tournament(
    name: str,
    description: str = "",
    clock_time: int = 10,
    clock_increment: int = 0,
    nb_rounds: int = 5,
    rated: bool = True,
    variant: str = "standard",
    position: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    password: str = "",
    team_id: str = "",
    min_rating: int = None,
    max_rating: int = None,
    nb_rated_games: int = None,
    chat_for: int = 0,
    allow_list: str = "",
    starts_at: str = None
) -> Optional[str]:
    """
    Cria um torneio suíço no Lichess e retorna o ID do torneio.

    Args:
        name: Nome do torneio (obrigatório)
        description: Descrição do torneio
        clock_time: Tempo inicial em minutos
        clock_increment: Incremento em segundos
        nb_rounds: Número de rodadas
        rated: Se vale rating
        variant: Variante do jogo ("standard", "chess960", etc.)
        position: Posição inicial em FEN
        password: Senha para entrar no torneio
        team_id: ID do time (OBRIGATÓRIO para Swiss tournaments)
        min_rating: Rating mínimo para participar
        max_rating: Rating máximo para participar
        nb_rated_games: Número mínimo de jogos rated
        chat_for: Quem pode conversar (0=ninguém, 10=membros, 20=todos)
        allow_list: Lista de usuários permitidos (separados por vírgula)
        starts_at: Data de início (formato ISO, ex: "2024-01-01T12:00:00Z")

    Returns:
        ID do torneio suíço no Lichess ou None em caso de erro
    """
    global _last_create_game_error
    _last_create_game_error = None

    token = os.environ.get('LICHESS_TOKEN')

    if not token:
        _last_create_game_error = "Token do Lichess não configurado. Configure a variável LICHESS_TOKEN."
        logger.error(_last_create_game_error)
        return None

    logger.warning(f"DEBUG: Token primeiros 10 chars: {token[:10]}...")
    logger.warning(f"DEBUG: Team ID: {team_id}")

    if not team_id:
        _last_create_game_error = "ID do time é obrigatório para criar torneios suíços no Lichess."
        logger.error(_last_create_game_error)
        return None

    url = f"{LICHESS_API_BASE}/api/team/{team_id}/swiss"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }

    data = {
        "name": name,
        "clockLimit": str(int(clock_time * 60)),
        "clockIncrement": str(clock_increment),
        "nbRounds": str(nb_rounds),
        "rated": "true" if rated else "false",
        "variant": variant
    }

    if description:
        data["description"] = description
    if position != "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1":
        data["position"] = position
    if password:
        data["password"] = password
    if min_rating is not None:
        data["minRating"] = str(min_rating)
    if max_rating is not None:
        data["maxRating"] = str(max_rating)
    if nb_rated_games is not None:
        data["minGames"] = str(nb_rated_games)
    if allow_list:
        data["allowList"] = allow_list
    if starts_at:
        data["startsAt"] = starts_at

    form_data = urlencode(data)

    max_retries = 10
    base_delay = 5

    for attempt in range(max_retries):
        async with ManagedClientSession() as session:
            try:
                logger.warning(f"DEBUG: Tentativa {attempt + 1} - Enviando POST para {url}")
                logger.warning(f"DEBUG: Form data: {form_data[:200]}")
                async with session.post(url, headers=headers, data=form_data, timeout=30) as resp:
                    logger.warning(f"DEBUG: Status HTTP: {resp.status}")
                    error_text = await resp.text()
                    logger.warning(f"DEBUG: Resposta: {error_text[:500]}")
                    if 200 <= resp.status < 300:
                        try:
                            result = await resp.json()
                            swiss_id = result.get('id')
                            if swiss_id:
                                _last_create_game_error = None
                                return swiss_id
                            else:
                                _last_create_game_error = "Resposta da API não contém ID do torneio suíço."
                                logger.error("Resposta da API do Lichess não contém ID: %s", result)
                                return None
                        except Exception as e:
                            _last_create_game_error = "Falha ao interpretar resposta da API."
                            logger.error("Erro ao interpretar resposta: %s", e)
                            return None
                    elif resp.status == 429:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Rate limiting detectado (429). Tentativa {attempt + 1}/{max_retries}. Aguardando {delay}s antes de tentar novamente.")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(delay)
                            continue
                        else:
                            error_text = await resp.text()
                            _last_create_game_error = f"Rate limiting persistente após {max_retries} tentativas: {error_text}"
                            logger.error("Rate limiting persistente: %s", error_text)
                            return None
                    else:
                        error_text = await resp.text()
                        if resp.status == 401:
                            _last_create_game_error = "Token do Lichess inválido."
                        elif resp.status == 400:
                            _last_create_game_error = f"Parâmetros inválidos: {error_text}"
                        elif resp.status == 404:
                            _last_create_game_error = f"Time '{team_id}' não encontrado ou token sem permissão 'tournament:write'. Verifique: 1) o time existe em lichess.org/@/{team_id}; 2) o token tem permissão de criar torneios."
                        else:
                            _last_create_game_error = f"Erro na API do Lichess: {resp.status}"
                        logger.error("Erro ao criar torneio suíço: %s", error_text)
                        return None
            except Exception as e:
                _last_create_game_error = f"Erro de conexão: {str(e)}"
                logger.error("Erro ao criar torneio suíço no Lichess: %s", e)
                return None

    _last_create_game_error = f"Falha após {max_retries} tentativas devido a rate limiting."
    return None

async def get_lichess_swiss_tournament_results(swiss_id: str) -> Optional[Dict]:
    """
    Busca os resultados de um torneio suíço no Lichess.

    Args:
        swiss_id: ID do torneio suíço no Lichess

    Returns:
        Dict com informações do torneio ou None
    """
    url = f"{LICHESS_API_BASE}/api/swiss/{swiss_id}/results"

    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=20) as resp:
                if resp.status == 200:
                    results = await resp.json()
                    return results
                else:
                    logger.warning(f"Erro ao buscar resultados do torneio suíço {swiss_id}: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Erro ao buscar resultados do torneio suíço {swiss_id}: {e}")
            return None

async def get_lichess_swiss_tournament_info(swiss_id: str) -> Optional[Dict]:
    """
    Busca informações de um torneio suíço no Lichess.

    Args:
        swiss_id: ID do torneio suíço no Lichess

    Returns:
        Dict com informações do torneio ou None
    """
    url = f"{LICHESS_API_BASE}/api/swiss/{swiss_id}"

    async with ManagedClientSession() as session:
        try:
            async with session.get(url, headers={"Accept": "application/json"}, timeout=20) as resp:
                if resp.status == 200:
                    info = await resp.json()
                    return info
                else:
                    logger.warning(f"Erro ao buscar info do torneio suíço {swiss_id}: {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Erro ao buscar info do torneio suíço {swiss_id}: {e}")
            return None
