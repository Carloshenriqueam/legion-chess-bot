import asyncio
import logging
from typing import Optional
from datetime import datetime
import traceback

import discord
import database
import lichess_api

from discord.ext import tasks

logger = logging.getLogger(__name__)

# Variáveis globais para controlar as tarefas em background
_monitor_instance = None
_scheduled_challenges_task = None

class ChallengeMonitor:
    def __init__(self, bot):
        self.bot = bot
        self.task = None

    def start(self):
        if self.task is None or self.task.cancelled():
            self.task = asyncio.create_task(self._run())
            logger.info("✅ Monitor de partidas iniciado!")

    async def get_swiss_standings_text(self, tournament_id: int) -> str:
        """Busca e formata a classificação atual do torneio suíço."""
        try:
            standings = await database.get_swiss_standings(tournament_id)
            if not standings:
                return "Nenhuma classificação disponível."

            # Formatar as top 5 posições
            standings_lines = []
            for i, player in enumerate(standings[:5], 1):
                try:
                    user = await self.bot.fetch_user(int(player['discord_id']))
                    display_name = user.display_name if user else player.get('discord_username', 'Desconhecido')
                except:
                    display_name = player.get('discord_username', 'Desconhecido')

                points = player.get('points', 0)
                wins = player.get('wins', 0)
                draws = player.get('draws', 0)
                losses = player.get('losses', 0)

                line = f"{i}. {display_name} - {points}pts ({wins}V/{draws}E/{losses}D)"
                standings_lines.append(line)

            return "\n".join(standings_lines)
        except Exception as e:
            logger.error(f"Erro ao buscar classificação suíça: {e}")
            return "Erro ao carregar classificação."

    async def _run(self):
        logger.info("🔄 Monitor de partidas rodando em modo MANUAL (processamento automático desabilitado)")
        logger.info("ℹ️ Use /check_games para processar manualmente ou clique no botão 'Finalizar Partida'")
        iteration = 0
        while True:
            try:
                iteration += 1
                if iteration % 60 == 0:  # A cada minuto (60 * 1s = 60s)
                    logger.info(f"⏰ Monitor rodando em modo standby (iteração {iteration})...")
                # Processamento automático foi desabilitado por solicitação do usuário
                # Apenas processamento manual via botão ou comando admin é permitido
            except Exception as e:
                logger.error(f"❌ Erro no monitor de partidas: {e}", exc_info=True)
            await asyncio.sleep(1)  # Verifica a cada 1 segundo para apenas manter a tarefa viva

    async def process_accepted_challenges(self):
        """Monitora partidas ativas e processa quando terminam."""
        # Busca desafios aceitos com link de jogo e sem registro em matches
        logger.info("🔍 Iniciando process_accepted_challenges()...")
        try:
            challenges = await database.get_finished_games_to_process()
            logger.info(f"📥 Recebidos {len(challenges) if challenges else 0} desafios da query")
        except Exception as e:
            logger.error(f"❌ Erro ao buscar desafios: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return

        if not challenges or len(challenges) == 0:
            return

        logger.info(f"🔍 Verificando {len(challenges)} partida(s) ativa(s)...")

        # Lista os IDs dos desafios encontrados (ou pairing_id para jogos suíços)
        challenge_ids = [ch.get('id') or ch.get('swiss_pairing_id') or 'unknown' for ch in challenges]
        logger.info(f"📋 IDs dos desafios encontrados: {challenge_ids}")

        for ch in challenges:
            game_url = ch.get('game_url')
            if not game_url:
                challenge_id = ch.get('id') or ch.get('swiss_pairing_id') or 'unknown'
                logger.warning(f"Desafio {challenge_id} não tem game_url")
                continue

            challenge_id = ch.get('id') or ch.get('swiss_pairing_id') or 'unknown'
            try:
                logger.info(f"Verificando partida {game_url} (desafio {challenge_id})...")
                outcome = await lichess_api.get_game_outcome(game_url)
                
                if not outcome:
                    logger.debug(f"Não foi possível obter resultado da partida {game_url}")
                    continue
                
                if not outcome.get('finished'):
                    logger.debug(f"Partida {game_url} ainda não terminou")
                    continue

                logger.info(f"Partida {game_url} terminou! Processando resultado...")

                # Resolve players by lichess username if available
                white_user = outcome['players']['white']['username']
                black_user = outcome['players']['black']['username']

                logger.info(f"🔍 Usuários Lichess na partida: White={white_user}, Black={black_user}")

                # is_rated do desafio interno (não do Lichess)
                is_rated = bool(ch.get('is_rated', False))
                logger.info(f"🎯 Processando jogo - ID: {challenge_id}, URL: {game_url}, Rated: {is_rated}")

                # Fetch player rows
                def _get_players():
                    conn = database.get_conn()
                    cur = conn.cursor()
                    p_white = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (white_user,)).fetchone() if white_user else None
                    p_black = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (black_user,)).fetchone() if black_user else None
                    conn.close()
                    return p_white, p_black

                p_white, p_black = await asyncio.to_thread(_get_players)

                # Verificar se é jogo de torneio suíço e definir player IDs adequadamente
                is_swiss_game = ch.get('swiss_pairing_id') is not None
                if is_swiss_game:
                    challenger_id = ch.get('player1_id')
                    challenged_id = ch.get('player2_id')
                    logger.info(f"🎯 Jogo suíço detectado: Player1={challenger_id}, Player2={challenged_id}")
                else:
                    challenger_id = ch['challenger_id']
                    challenged_id = ch['challenged_id']

                # Convert sqlite3.Row to dict for easier access
                p_white = dict(p_white) if p_white else None
                p_black = dict(p_black) if p_black else None

                logger.info(f"🔍 Mapeamento Discord/Lichess: Challenger={challenger_id}, Challenged={challenged_id}")
                logger.info(f"🔍 Players encontrados: White={p_white['discord_id'] if p_white else None}, Black={p_black['discord_id'] if p_black else None}")

                # SIMPLIFICADO: Attempt to determine winner/loser
                winner_id = None
                loser_id = None
                mode = ch.get('time_control_mode', 'blitz')
                is_draw = outcome.get('is_draw', False)
                rating_changes = None

                if is_draw:
                    result = 'draw'
                    winner_id = None
                    loser_id = None
                    logger.info(f"🏁 Partida {game_url} terminou em empate")
                else:
                    # SIMPLIFICADO: winner by color or username
                    winner_color = outcome.get('winner_color')
                    winner_username = outcome.get('winner_username')

                    logger.info(f"🏆 Vencedor detectado: Color={winner_color}, Username={winner_username}")

                    # Método 1: Mapear diretamente por username do Lichess
                    if winner_username:
                        logger.info(f"🔍 Tentando mapear por username: {winner_username}")
                        if p_white and p_white.get('lichess_username') == winner_username:
                            winner_id = p_white['discord_id']
                            loser_id = p_black['discord_id'] if p_black else (challenged_id if winner_id == challenger_id else challenger_id)
                            logger.info(f"✅ Mapeado por username: Winner={winner_id} (white), Loser={loser_id}")
                        elif p_black and p_black.get('lichess_username') == winner_username:
                            winner_id = p_black['discord_id']
                            loser_id = p_white['discord_id'] if p_white else (challenger_id if winner_id == challenged_id else challenger_id)
                            logger.info(f"✅ Mapeado por username: Winner={winner_id} (black), Loser={loser_id}")

                    # Método 2: Mapear por cor das peças (fallback)
                    if not winner_id and winner_color:
                        logger.info(f"🔍 Tentando mapear por cor: {winner_color}")
                        if winner_color == 'white' and p_white:
                            winner_id = p_white['discord_id']
                            loser_id = p_black['discord_id'] if p_black else (challenged_id if winner_id == challenger_id else challenger_id)
                            logger.info(f"✅ Mapeado por cor: Winner={winner_id} (white), Loser={loser_id}")
                        elif winner_color == 'black' and p_black:
                            winner_id = p_black['discord_id']
                            loser_id = p_white['discord_id'] if p_white else (challenger_id if winner_id == challenged_id else challenger_id)
                            logger.info(f"✅ Mapeado por cor: Winner={winner_id} (black), Loser={loser_id}")

                    # Método 3: Fallback baseado na lógica do desafio (challenger vs challenged)
                    if not winner_id:
                        logger.warning(f"⚠️ Não foi possível mapear vencedor para desafio {challenge_id}. Usando fallback baseado no desafio.")
                        logger.warning(f"   Challenger: {challenger_id}, Challenged: {challenged_id}")
                        logger.warning(f"   Winner color: {winner_color}, Winner username: {winner_username}")

                        # Determina vencedor baseado na cor e quem desafiou
                        if winner_color == 'white':
                            # Verifica se challenger estava nas brancas
                            if p_white and p_white['discord_id'] == challenger_id:
                                winner_id = challenger_id
                                loser_id = challenged_id
                            elif p_black and p_black['discord_id'] == challenger_id:
                                # Challenger estava nas pretas, então challenged venceu (brancas)
                                winner_id = challenged_id
                                loser_id = challenger_id
                            else:
                                # Fallback: assume challenger venceu
                                winner_id = challenger_id
                                loser_id = challenged_id
                        elif winner_color == 'black':
                            # Verifica se challenger estava nas pretas
                            if p_black and p_black['discord_id'] == challenger_id:
                                winner_id = challenger_id
                                loser_id = challenged_id
                            elif p_white and p_white['discord_id'] == challenger_id:
                                # Challenger estava nas brancas, então challenged venceu (pretas)
                                winner_id = challenged_id
                                loser_id = challenger_id
                            else:
                                # Fallback: assume challenger venceu
                                winner_id = challenger_id
                                loser_id = challenged_id
                        else:
                            # Sem cor definida, usa challenger como vencedor
                            winner_id = challenger_id
                            loser_id = challenged_id

                        logger.warning(f"⚠️ Fallback usado: Winner={winner_id}, Loser={loser_id}")

                    # Garante que temos um loser_id
                    if winner_id and not loser_id:
                        loser_id = challenged_id if winner_id == challenger_id else challenger_id

                    result = 'win'
                    logger.info(f"🏆 Resultado final: {winner_id} venceu {loser_id}")

                # Persist result (só para jogos não-suíços)
                if not is_swiss_game:
                    # Determine linked status for white/black (players linked to our DB)
                    linked_white = bool(p_white)
                    linked_black = bool(p_black)

                    # If both players are anonymous/unlinked: mark finished but do NOT update stats/ratings
                    if not linked_white and not linked_black:
                        await database.mark_challenge_as_finished(ch['id'], None, None, 'void', outcome.get('pgn') or ch.get('game_url'))
                        await database.update_challenge_status(ch['id'], 'finished')
                        logger.info(f"Desafio {ch['id']} marcado como finalizado (ambos anônimos — sem atualização de stats/ratings)")
                        # Skip rating/stats update
                        skip_stats_update = True
                    else:
                        # If only one player is linked, override the recorded winner to be the linked player
                        if linked_white and not linked_black:
                            linked_player = p_white['discord_id']
                            other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                            # Register the linked player as the winner regardless of actual outcome
                            winner_id = linked_player
                            loser_id = other_player
                            result = 'win'
                            await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                            await database.update_challenge_status(ch['id'], 'finished')
                            logger.info(f"Desafio {ch['id']} marcado como finalizado (um anônimo presente) — vencedor registrado: {winner_id}")
                            skip_stats_update = False
                        elif linked_black and not linked_white:
                            linked_player = p_black['discord_id']
                            other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                            winner_id = linked_player
                            loser_id = other_player
                            result = 'win'
                            await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                            await database.update_challenge_status(ch['id'], 'finished')
                            logger.info(f"Desafio {ch['id']} marcado como finalizado (um anônimo presente) — vencedor registrado: {winner_id}")
                            skip_stats_update = False
                        else:
                            # Both players linked — record the actual outcome
                            await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                            await database.update_challenge_status(ch['id'], 'finished')
                            logger.info(f"Desafio {ch['id']} marcado como finalizado")
                            skip_stats_update = False

                # Update internal stats/ratings
                try:
                    if skip_stats_update:
                        # Nothing to do for anonymous vs anonymous
                        pass
                    else:
                        # If result is a win, determine who should receive stats/ratings
                        if result == 'win' and winner_id and loser_id:
                            # If one side is anonymous, award stats/ratings to the linked player
                            if p_white and not p_black:
                                linked_player = p_white['discord_id']
                                other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                                await database.update_player_stats(linked_player, mode, 'win')
                                await database.update_player_stats(other_player, mode, 'loss')
                                logger.info(f"Estatísticas atualizadas (um anônimo presente): {linked_player} (win), {other_player} (loss)")
                                await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                                if is_rated:
                                    rating_changes = await database.apply_match_ratings(linked_player, other_player, mode)
                                    if rating_changes:
                                        logger.info(f"Ratings atualizados para desafio {ch.get('id')} (um anônimo presente)")
                                        await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                            elif p_black and not p_white:
                                linked_player = p_black['discord_id']
                                other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                                await database.update_player_stats(linked_player, mode, 'win')
                                await database.update_player_stats(other_player, mode, 'loss')
                                logger.info(f"Estatísticas atualizadas (um anônimo presente): {linked_player} (win), {other_player} (loss)")
                                if is_rated:
                                    rating_changes = await database.apply_match_ratings(linked_player, other_player, mode)
                                    if rating_changes:
                                        logger.info(f"Ratings atualizados para desafio {ch.get('id')} (um anônimo presente)")
                            else:
                                # Both players linked — standard flow
                                if not is_swiss_game:
                                    await database.update_player_stats(winner_id, mode, 'win')
                                    await database.update_player_stats(loser_id, mode, 'loss')
                                    logger.info(f"Estatísticas atualizadas: {winner_id} (win), {loser_id} (loss)")

                                    await database.check_and_unlock_achievements(winner_id, mode, 'win', loser_id)
                                    await database.check_and_unlock_achievements(loser_id, mode, 'loss', winner_id)

                                    # Sempre atualiza rating se is_rated=True
                                    if is_rated:
                                        rating_changes = await database.apply_match_ratings(winner_id, loser_id, mode)
                                        if rating_changes:
                                            logger.info(f"Ratings atualizados para desafio {ch.get('id')}")
                                            await database.check_and_unlock_achievements(winner_id, mode, 'win', loser_id)
                                            await database.check_and_unlock_achievements(loser_id, mode, 'loss', winner_id)
                                            try:
                                                from cogs.rankings import Rankings
                                                rankings_cog = self.bot.get_cog('Rankings')
                                                if rankings_cog:
                                                    await rankings_cog.update_fixed_ranking()
                                            except Exception as e:
                                                logger.error(f"Erro ao atualizar ranking fixo para desafio {ch.get('id')}: {e}")
                                        else:
                                            logger.warning(f"Falha ao atualizar ratings para desafio {ch.get('id')}")
                                else:
                                    logger.info(f"Jogo suíço finalizado: {winner_id} venceu {loser_id} (sem atualização de ratings)")
                        elif result == 'draw':
                            # Para jogos suíços, não atualizar ratings internos
                            if not is_swiss_game:
                                # In draw, credit draw to both participants if they are linked
                                if challenger_id and (p_white or p_black):
                                    if p_white and p_white.get('discord_id'):
                                        await database.update_player_stats(p_white['discord_id'], mode, 'draw')
                                    if p_black and p_black.get('discord_id'):
                                        await database.update_player_stats(p_black['discord_id'], mode, 'draw')
                                    logger.info(f"Estatísticas atualizadas (empate): {p_white['discord_id'] if p_white else 'anon'}, {p_black['discord_id'] if p_black else 'anon'}")

                                if is_rated and challenger_id and challenged_id and (p_white or p_black):
                                    # Only apply draw rating if at least one side linked — apply to linked players
                                    players_for_rating = []
                                    if p_white and p_white.get('discord_id'):
                                        players_for_rating.append(p_white['discord_id'])
                                    if p_black and p_black.get('discord_id'):
                                        players_for_rating.append(p_black['discord_id'])
                                    if len(players_for_rating) == 2:
                                        rating_changes = await database.apply_draw_ratings(players_for_rating[0], players_for_rating[1], mode)
                                        if rating_changes:
                                            logger.info(f"Ratings atualizados (empate) para desafio {ch.get('id')}")
                except Exception as e:
                    logger.error(f"Failed to update stats/ratings for challenge {challenge_id}: {e}", exc_info=True)

                # Salvar partida no histórico
                try:
                    p1_id, p2_id = (challenger_id, challenged_id)
                    
                    # Buscar nomes dos jogadores
                    def _get_player_names():
                        conn = database.get_conn()
                        cur = conn.cursor()
                        p1 = cur.execute("SELECT discord_username FROM players WHERE discord_id = ?", (p1_id,)).fetchone()
                        p2 = cur.execute("SELECT discord_username FROM players WHERE discord_id = ?", (p2_id,)).fetchone()
                        conn.close()
                        return p1[0] if p1 else str(p1_id), p2[0] if p2 else str(p2_id)
                    
                    p1_name, p2_name = await asyncio.to_thread(_get_player_names)
                    
                    if is_swiss_game:
                        p1_name = ch.get('player1_name', p1_name)
                        p2_name = ch.get('player2_name', p2_name)

                    p1_rating_before, p2_rating_before = (None, None)
                    p1_rating_after, p2_rating_after = (None, None)

                    if rating_changes:
                        if result == 'win':
                            winner_data = rating_changes.get('winner', {})
                            loser_data = rating_changes.get('loser', {})
                            if winner_id == p1_id:
                                p1_rating_before = winner_data.get('old_rating')
                                p1_rating_after = winner_data.get('new_rating')
                                p2_rating_before = loser_data.get('old_rating')
                                p2_rating_after = loser_data.get('new_rating')
                            else:
                                p1_rating_before = loser_data.get('old_rating')
                                p1_rating_after = loser_data.get('new_rating')
                                p2_rating_before = winner_data.get('old_rating')
                                p2_rating_after = winner_data.get('new_rating')
                        elif result == 'draw':
                            p1_data = rating_changes.get('player1', {})
                            p2_data = rating_changes.get('player2', {})
                            p1_rating_before = p1_data.get('old')
                            p1_rating_after = p1_data.get('new')
                            p2_rating_before = p2_data.get('old')
                            p2_rating_after = p2_data.get('new')
                    
                    await database.save_game_history(
                        player1_id=p1_id,
                        player2_id=p2_id,
                        player1_name=p1_name,
                        player2_name=p2_name,
                        winner_id=winner_id,
                        result=result,
                        mode=mode,
                        time_control=ch.get('time_control'),
                        game_url=game_url,
                        p1_rating_before=p1_rating_before,
                        p2_rating_before=p2_rating_before,
                        p1_rating_after=p1_rating_after,
                        p2_rating_after=p2_rating_after,
                    )
                    logger.info(f"Partida salva no histórico para desafio {challenge_id}")
                except Exception as e:
                    logger.error(f"Erro ao salvar partida no histórico para desafio {challenge_id}: {e}", exc_info=True)


                # Verificar se é torneio (para atualizar standings se necessário)
                try:
                    # Check if this is a tournament challenge
                    if ch.get('id'):  # Só buscar se for um challenge regular
                        tournament_match = await database.get_tournament_match_by_challenge(ch['id'])
                    else:
                        tournament_match = None

                    # Check if this is a Swiss tournament challenge
                    swiss_pairing = None
                    if not tournament_match and ch.get('id'):
                        swiss_pairing = await database.get_swiss_pairing_by_challenge(ch['id'])
                        logger.info(f"🔍 Swiss pairing por challenge {ch['id']}: {swiss_pairing}")

                    # Also check for Swiss pairings with game URLs (new system)
                    swiss_game_pairing = None
                    if not swiss_pairing:
                        swiss_game_pairing = await database.get_swiss_pairing_by_game_url(ch.get('game_url'))
                        logger.info(f"🔍 Swiss pairing por game_url {ch.get('game_url')}: {swiss_game_pairing}")

                    if swiss_pairing or swiss_game_pairing:
                        # Determinar qual pairing usar
                        active_pairing = swiss_pairing or swiss_game_pairing
                        logger.info(f"🎯 Pairing Swiss encontrado: {active_pairing['id']}, swiss_pairing={swiss_pairing is not None}, swiss_game_pairing={swiss_game_pairing is not None}")

                        # Atualizar o pairing suíço e standings
                        logger.info(f"Atualizando pairing Swiss {active_pairing['id']} com resultado: {result}")

                        # Aplicar regras de contas anônimas para torneios suíços:
                        # - Se ambos anônimos -> winner_id_final = None (partida não vale)
                        # - Se apenas um estiver vinculado -> winner_id_final = discord_id do jogador vinculado
                        # - Se ambos vinculados -> winner_id_final = winner_id (mapeado acima)
                        winner_id_final = None
                        try:
                            linked_white = bool(p_white)
                            linked_black = bool(p_black)
                        except NameError:
                            linked_white = False
                            linked_black = False

                        if result == 'win':
                            if not linked_white and not linked_black:
                                winner_id_final = None
                                logger.info(f"Swiss pairing {active_pairing['id']}: ambos anônimos -> sem vencedor registrado para standings")
                            elif linked_white and not linked_black:
                                winner_id_final = p_white['discord_id']
                                logger.info(f"Swiss pairing {active_pairing['id']}: apenas white vinculado -> vencedor forçado: {winner_id_final}")
                            elif linked_black and not linked_white:
                                winner_id_final = p_black['discord_id']
                                logger.info(f"Swiss pairing {active_pairing['id']}: apenas black vinculado -> vencedor forçado: {winner_id_final}")
                            else:
                                # ambos vinculados
                                winner_id_final = winner_id
                                logger.info(f"Swiss pairing {active_pairing['id']}: ambos vinculados -> vencedor real: {winner_id_final}")
                        else:
                            winner_id_final = None

                        await database.finish_swiss_pairing(
                            tournament_id=active_pairing['tournament_id'],
                            pairing_id=active_pairing['id'],
                            winner_id=winner_id_final,
                            challenge_id=ch['id'] if swiss_pairing else None  # Só passa challenge_id se for o sistema antigo
                        )
                        logger.info(f"Pairing Swiss {active_pairing['id']} finalizado e standings atualizados (winner={winner_id_final})")

                        # Ajustar variáveis locais para refletir o vencedor efetivo usado no pairing
                        if winner_id_final is None:
                            # Partida não vale para standings/rating
                            result = 'void'
                            winner_id = None
                            loser_id = None
                        else:
                            # Garantir que winner_id e loser_id apontem para os discord_ids corretos
                            winner_id = str(winner_id_final)
                            # Tentar inferir o loser
                            if p_white and p_white.get('discord_id') and str(p_white['discord_id']) == str(winner_id_final):
                                loser_id = p_black['discord_id'] if p_black else challenged_id
                            elif p_black and p_black.get('discord_id') and str(p_black['discord_id']) == str(winner_id_final):
                                loser_id = p_white['discord_id'] if p_white else challenger_id
                            else:
                                # Fallback: use challenger/challenged mapping
                                loser_id = challenged_id if str(winner_id_final) == str(challenger_id) else challenger_id

                        # Adicionar classificação do torneio às DMs
                        tournament_standings = await self.get_swiss_standings_text(active_pairing['tournament_id'])
                except Exception as e:
                    logger.error(f"Erro ao verificar torneio para desafio {ch['id']}: {e}")

                # Preparar dados comuns para DMs
                    reason = outcome.get('reason', 'unknown')
                    url = ch.get('game_url')

                    logger.info(f"Processando jogo: swiss_pairing_id={ch.get('swiss_pairing_id')}, is_swiss_game={is_swiss_game}, game_url={ch.get('game_url')}")

                    # Para jogos suíços, usar campos diferentes
                    if is_swiss_game:
                        challenger_name = ch.get('player1_name')
                        challenged_name = ch.get('player2_name')
                        time_control = "10+0"  # Usar padrão para torneios suíços
                        is_rated = False  # Torneios suíços não são rated
                    else:
                        challenger_name = ch.get('challenger_name')
                        challenged_name = ch.get('challenged_name')
                        time_control = ch.get('time_control')
                        is_rated = ch.get('is_rated')

                    # Formata mudanças de rating (só para jogos não-suíços)
                    rating_text = ""
                    if not is_swiss_game and rating_changes:
                        try:
                            parts = []
                            # rating_changes é um dict com 'winner' e 'loser'
                            for player_type, data in rating_changes.items():
                                if isinstance(data, dict) and 'new_rating' in data and 'change' in data:
                                    # Tentar encontrar o ID do jogador baseado no tipo
                                    player_id = winner_id if player_type == 'winner' else loser_id
                                    if player_id:
                                        new_rating = data['new_rating']
                                        change = data['change']
                                        parts.append(f"<@{player_id}> {new_rating} ({change:+})")
                            rating_text = " | ".join(parts)
                            logger.info(f"📈 Mudanças de rating: {rating_text}")
                        except Exception as e:
                            logger.error(f"Erro ao formatar mudanças de rating para desafio {ch.get('id')}: {e}")
                            rating_text = ""

                    # Estatísticas da partida
                    game_stats = outcome.get('game_stats', {})
                    moves = game_stats.get('moves')
                    time_text = time_control or "?"

                    # Verificar se é torneio suíço para incluir classificação
                    is_swiss_tournament = swiss_pairing is not None or swiss_game_pairing is not None or is_swiss_game
                    tournament_standings = tournament_standings if is_swiss_tournament else None
                    reason_text = reason

                    # Enviar DMs para os jogadores SEMPRE (independentemente do canal)
                    try:
                        logger.info(f"📱 Enviando DMs para jogadores do desafio {ch['id']} (suíço: {is_swiss_game})")
                        logger.info(f"📱 Players: {challenger_id} vs {challenged_id}, Winner: {winner_id}, Result: {result}")
                        # Enviar DMs para ambos os jogadores
                        for player_id in [challenger_id, challenged_id]:
                            try:
                                # Determinar resultado específico para este jogador
                                if result == 'draw':
                                    player_result_text = "Empate"
                                    opponent_id = challenged_id if player_id == challenger_id else challenger_id
                                else:
                                    is_winner = player_id == winner_id
                                    player_result_text = "Vitória" if is_winner else "Derrota"
                                    opponent_id = challenged_id if player_id == challenger_id else challenger_id

                                # Informação adicional sobre efeitos de rating/stat
                                anon_info_text = None
                                try:
                                    both_anonymous = (not p_white and not p_black)
                                    one_anonymous = (bool(p_white) ^ bool(p_black))
                                except NameError:
                                    both_anonymous = False
                                    one_anonymous = False

                                if 'skip_stats_update' in locals() and skip_stats_update:
                                    anon_info_text = "A partida envolveu jogadores anônimos — nenhum efeito de rating/stat será aplicado."
                                elif one_anonymous:
                                    # Determine which side is linked
                                    if p_white and not p_black:
                                        linked_name = challenger_name if challenger_name else 'Jogador vinculado'
                                    elif p_black and not p_white:
                                        linked_name = challenged_name if challenged_name else 'Jogador vinculado'
                                    else:
                                        linked_name = 'Jogador vinculado'
                                    anon_info_text = f"Um dos jogadores jogou como anônimo. Apenas {linked_name} receberá efeitos em estatísticas/rating." 

                                # Criar embed personalizado para este jogador
                                player_dm_embed = discord.Embed(
                                    title="🏁 Sua Partida Terminou!",
                                    color=0xCD0000,
                                    description=f"Resultado: **{player_result_text}**"
                                )
                                player_dm_embed.add_field(
                                    name="Oponente",
                                    value=f"<@{opponent_id}>",
                                    inline=True
                                )
                                player_dm_embed.add_field(
                                    name="Tempo",
                                    value=time_text,
                                    inline=True
                                )
                                player_dm_embed.add_field(
                                    name="Link da Partida",
                                    value=f"[Ver partida completa]({url})",
                                    inline=False
                                )

                                if rating_changes:
                                    player_dm_embed.add_field(
                                        name="📊 Mudanças de Rating",
                                        value=rating_text,
                                        inline=False
                                    )

                                # Adicionar classificação se for torneio suíço
                                if is_swiss_tournament and tournament_standings:
                                    player_dm_embed.add_field(
                                        name="🏆 Classificação Atual do Torneio",
                                        value=tournament_standings,
                                        inline=False
                                    )

                                # Adicionar nota sobre contas anônimas / rating
                                if anon_info_text:
                                    player_dm_embed.add_field(
                                        name="⚠️ Observação",
                                        value=anon_info_text,
                                        inline=False
                                    )

                                # Enviar DM
                                player_user = await self.bot.fetch_user(int(player_id))
                                if player_user:
                                    await player_user.send(embed=player_dm_embed)
                                    logger.info(f"✅ DM enviada para jogador {player_id} ({player_result_text})")
                                else:
                                    logger.warning(f"Não foi possível encontrar usuário Discord para {player_id}")

                            except Exception as e:
                                logger.warning(f"Não foi possível enviar DM para jogador {player_id}: {e}")

                    except Exception as e:
                        logger.error(f"Erro ao enviar DMs para desafio {ch['id']}: {e}")

                    # Resultados enviados apenas via DM - sem anúncios no canal
                    logger.info(f"✅ Resultado enviado via DM para desafio {ch['id']}")
                except Exception as e:
                    logger.error(f"Failed to send DM result for challenge {ch['id']}: {e}", exc_info=True)

            except Exception as e:
                logger.error(f"Erro ao processar desafio {ch['id']}: {e}", exc_info=True)
                continue

# Helper to integrate with bot
_monitor_instance: Optional[ChallengeMonitor] = None

def setup_challenge_monitor(bot):
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ChallengeMonitor(bot)
    _monitor_instance.start()

# Backwards compatibility shim for cogs that expect tasks.set_bot_instance(bot)
# Some modules may call this during setup; delegate to setup_challenge_monitor

def set_bot_instance(bot):
    setup_challenge_monitor(bot)


async def start_background_tasks():
    """Compat helper chamada pelo main para iniciar o monitor."""
    if _monitor_instance is None:
        logger.warning("⚠️ Challenge monitor ainda não foi configurado. Chame set_bot_instance(bot) antes de iniciar.")
        return
    logger.info("Iniciando monitor de partidas via start_background_tasks()...")
    _monitor_instance.start()

async def check_finished_games():
    """Função para verificação manual de partidas finalizadas (usada pelo comando /check_games)."""
    if _monitor_instance is None:
        logger.warning("⚠️ Challenge monitor não foi configurado.")
        return
    await _monitor_instance.process_accepted_challenges()

async def cleanup_invalid_games():
    """Limpa jogos que não existem mais no Lichess (URLs inválidas)."""
    try:
        logger.info("🧹 Iniciando limpeza de jogos inválidos...")

        # Buscar jogos 'accepted' não processados
        def _fetch():
            conn = database.get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.id, c.game_url
                FROM challenges c
                WHERE c.status = 'accepted' AND c.game_url IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
            """)
            games = cursor.fetchall()
            conn.close()
            return games

        games = await asyncio.to_thread(_fetch)
        logger.info(f"📋 Encontrados {len(games)} jogos para verificar")

        invalid_games = []
        for game in games:
            try:
                outcome = await lichess_api.get_game_outcome(game['game_url'])
                if outcome is None:
                    invalid_games.append(game['id'])
            except Exception as e:
                logger.debug(f"Erro ao verificar jogo {game['id']}: {e}")
                invalid_games.append(game['id'])

        if invalid_games:
            logger.info(f"🗑️ Limpando {len(invalid_games)} jogos inválidos...")
            def _clean():
                conn = database.get_conn()
                cursor = conn.cursor()
                for game_id in invalid_games:
                    cursor.execute("UPDATE challenges SET game_url = NULL, status = 'pending' WHERE id = ?", (game_id,))
                conn.commit()
                conn.close()

            await asyncio.to_thread(_clean)
            logger.info("✅ Limpeza de jogos inválidos concluída!")
        else:
            logger.info("✅ Nenhum jogo inválido encontrado.")

    except Exception as e:
        logger.error(f"❌ Erro na limpeza de jogos inválidos: {e}")

async def create_result_embeds(bot, ch, outcome, winner_id, loser_id, result, rating_changes, p_white, p_black):
    """Cria os embeds do resultado da partida (usado tanto para canal quanto para DM)."""
    reason = outcome.get('reason', 'unknown')
    url = ch.get('game_url')

    # Formata mudanças de rating
    rating_text = ""
    logger.info(f"📊 Processando rating_changes: {rating_changes}")
    if rating_changes:
        try:
            parts = []
            # rating_changes é um dict com 'winner' e 'loser'
            for player_type, data in rating_changes.items():
                logger.info(f"📊 Processando {player_type}: {data}")
                if isinstance(data, dict) and 'new_rating' in data and 'change' in data:
                    # Tentar encontrar o ID do jogador baseado no tipo
                    player_id = winner_id if player_type == 'winner' else loser_id
                    if player_id:
                        new_rating = data['new_rating']
                        change = data['change']
                        parts.append(f"<@{player_id}> {new_rating} ({change:+})")
            rating_text = " | ".join(parts)
            logger.info(f"📈 Mudanças de rating formatadas: {rating_text}")
        except Exception as e:
            logger.error(f"Erro ao formatar mudanças de rating para desafio {ch['id']}: {e}")
            rating_text = ""

    # Obter menções dos jogadores
    winner_mention = None
    loser_mention = None
    white_mention = None
    black_mention = None

    # Tenta obter menções dos usuários
    try:
        if winner_id:
            user = await bot.fetch_user(int(winner_id))
            winner_mention = user.mention
        if loser_id:
            user = await bot.fetch_user(int(loser_id))
            loser_mention = user.mention
        logger.info(f"👤 Menções obtidas: Winner={winner_mention}, Loser={loser_mention}")
    except Exception as e:
        logger.warning(f"Erro ao buscar usuários para menção: {e}")
        # Fallback para menção simples
        if winner_id:
            winner_mention = f"<@{winner_id}>"
        if loser_id:
            loser_mention = f"<@{loser_id}>"

    # Se ainda não temos menções, tentar mapear pelos jogadores do Lichess
    if not winner_mention and p_white and p_black:
        try:
            if result == 'win':
                # Determinar quem venceu baseado nas cores
                players = outcome.get('players', {})
                winner_color = outcome.get('winner_color')
                if winner_color == 'white' and p_white:
                    winner_mention = f"<@{p_white['discord_id']}>"
                    loser_mention = f"<@{p_black['discord_id']}>"
                elif winner_color == 'black' and p_black:
                    winner_mention = f"<@{p_black['discord_id']}>"
                    loser_mention = f"<@{p_white['discord_id']}>"
            elif result == 'draw':
                # Para empate, não há winner/loser específicos
                pass
        except Exception as e:
            logger.warning(f"Erro ao mapear winner/loser por cores: {e}")

    # Garantir que sempre temos alguma menção
    if not winner_mention and winner_id:
        winner_mention = f"<@{winner_id}>"
    if not loser_mention and loser_id:
        loser_mention = f"<@{loser_id}>"

    # Mapear cores dos jogadores
    players = outcome.get('players', {})
    white_user = players.get('white', {}).get('username')
    black_user = players.get('black', {}).get('username')

    # Tentar encontrar menções do Discord baseadas nos usernames do Lichess
    if white_user:
        try:
            white_player = await asyncio.to_thread(
                lambda: database.get_conn().execute(
                    "SELECT discord_id FROM players WHERE lichess_username = ?",
                    (white_user,)
                ).fetchone()
            )
            if white_player:
                white_mention = f"<@{white_player['discord_id']}>"
        except Exception as e:
            logger.warning(f"Erro ao buscar Discord user para white player {white_user}: {e}")

    if black_user:
        try:
            black_player = await asyncio.to_thread(
                lambda: database.get_conn().execute(
                    "SELECT discord_id FROM players WHERE lichess_username = ?",
                    (black_user,)
                ).fetchone()
            )
            if black_player:
                black_mention = f"<@{black_player['discord_id']}>"
        except Exception as e:
            logger.warning(f"Erro ao buscar Discord user para black player {black_user}: {e}")

    # Primeiro embed: Resultado principal
    embed1 = discord.Embed(
        title="🏁 ➜ Partida Finalizada!",
        color=0xCD0000,
        description=f"🔗 [Ver partida completa]({url})"
    )

    if result == 'draw':
        embed1.add_field(
            name="📊 ➜ Resultado",
            value="**Empate**",
            inline=False
        )
    else:
        embed1.add_field(
            name="✅ ➜ Win",
            value=winner_mention or 'Desconhecido',
            inline=True
        )
        embed1.add_field(
            name="❌ ➜ Loser",
            value=loser_mention or 'Desconhecido',
            inline=True
        )

    # Segundo embed: Jogadores por cor
    embed2 = discord.Embed(
        title="♟️ Jogadores",
        color=0xCD0000
    )
    embed2.add_field(
        name="Brancas",
        value=white_mention or 'Desconhecido',
        inline=True
    )
    embed2.add_field(
        name="Pretas",
        value=black_mention or 'Desconhecido',
        inline=True
    )

    # Terceiro embed: Estatísticas da partida
    embed3 = discord.Embed(
        title="📊 ➜ Estatísticas",
        color=0xCD0000
    )

    game_stats = outcome.get('game_stats', {})
    moves = game_stats.get('moves')
    time_control = game_stats.get('time_control')

    moves_text = f"{moves // 2 if moves and moves % 2 == 0 else (moves // 2) + 1 if moves else '?'}"
    time_text = time_control or "?"
    reason_text = reason

    embed3.add_field(
        name="Tempo",
        value=time_text,
        inline=True
    )
    embed3.add_field(
        name="Motivo do Fim",
        value=reason_text,
        inline=True
    )

    # Nota sobre contas anônimas / efeito em rating
    anon_info_text = None
    try:
        linked_white = bool(p_white)
        linked_black = bool(p_black)
    except NameError:
        linked_white = False
        linked_black = False

    if not linked_white and not linked_black:
        anon_info_text = "Ambos os jogadores usaram contas anônimas — nenhum efeito de rating/estatísticas foi aplicado."
    elif linked_white and not linked_black:
        # linked white player receives effects
        linked_mention = None
        try:
            if p_white and p_white.get('discord_id'):
                linked_mention = f"<@{p_white['discord_id']}>"
        except Exception:
            linked_mention = None
        anon_info_text = f"Um dos jogadores jogou como anônimo. Apenas {linked_mention or 'o jogador vinculado'} recebeu efeitos em estatísticas/rating."
    elif linked_black and not linked_white:
        linked_mention = None
        try:
            if p_black and p_black.get('discord_id'):
                linked_mention = f"<@{p_black['discord_id']}>"
        except Exception:
            linked_mention = None
        anon_info_text = f"Um dos jogadores jogou como anônimo. Apenas {linked_mention or 'o jogador vinculado'} recebeu efeitos em estatísticas/rating."

    # Quarto embed: Mudanças de rating (se houver) and possible anon note
    embeds_to_send = [embed1, embed2, embed3]
    if anon_info_text:
        embed_note = discord.Embed(
            title="⚠️ Observação",
            color=0xE67E22,
            description=anon_info_text
        )
        embeds_to_send.append(embed_note)

    if rating_text:
        embed4 = discord.Embed(
            title="📈 ➜ Mudanças de Rating",
            color=0xCD0000,
            description=rating_text
        )
        embeds_to_send.append(embed4)

    return embeds_to_send

async def process_challenge_result(bot, ch):
    """Processa o resultado de um desafio individual (usado para finalização manual)."""
    game_url = ch.get('game_url')
    if not game_url:
        logger.warning(f"Desafio {ch['id']} não tem game_url")
        return False

    try:
        logger.info(f"Verificando partida {game_url} (desafio {ch['id']})...")
        outcome = await lichess_api.get_game_outcome(game_url)

        if not outcome:
            logger.debug(f"Não foi possível obter resultado da partida {game_url}")
            return False

        if not outcome.get('finished'):
            logger.debug(f"Partida {game_url} ainda não terminou")
            return False

        logger.info(f"Partida {game_url} terminou! Processando resultado...")

        # Resolve players by lichess username if available
        white_user = outcome['players']['white']['username']
        black_user = outcome['players']['black']['username']

        logger.info(f"🔍 Usuários Lichess na partida: White={white_user}, Black={black_user}")

        # is_rated do desafio interno (não do Lichess)
        is_rated = bool(ch.get('is_rated', False))

        # Fetch player rows
        def _get_players():
            conn = database.get_conn()
            cur = conn.cursor()
            p_white = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (white_user,)).fetchone() if white_user else None
            p_black = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (black_user,)).fetchone() if black_user else None
            conn.close()
            return p_white, p_black

        p_white, p_black = await asyncio.to_thread(_get_players)
        challenger_id = ch['challenger_id']
        challenged_id = ch['challenged_id']

        # Convert sqlite3.Row to dict for easier access
        p_white = dict(p_white) if p_white else None
        p_black = dict(p_black) if p_black else None

        logger.info(f"🔍 Mapeamento Discord/Lichess: Challenger={challenger_id}, Challenged={challenged_id}")
        logger.info(f"🔍 Players encontrados: White={p_white['discord_id'] if p_white else None}, Black={p_black['discord_id'] if p_black else None}")
        logger.info(f"🔍 Outcome data: winner_color={outcome.get('winner_color')}, winner_username={outcome.get('winner_username')}, is_draw={outcome.get('is_draw')}")

        # SIMPLIFICADO: Attempt to determine winner/loser
        winner_id = None
        loser_id = None
        mode = ch.get('time_control_mode', 'blitz')
        is_draw = outcome.get('is_draw', False)
        rating_changes = None

        if is_draw:
            result = 'draw'
            winner_id = None
            loser_id = None
            logger.info(f"🏁 Partida {game_url} terminou em empate")
        else:
            # Determinar winner/loser com prioridade para mapeamento por cor
            winner_color = outcome.get('winner_color')
            winner_username = outcome.get('winner_username')

            logger.info(f"🏆 Vencedor detectado: Color={winner_color}, Username={winner_username}")
            logger.info(f"🏆 Players: White={white_user}, Black={black_user}")

            # Método 1: Mapear diretamente por username do Lichess
            if winner_username:
                logger.info(f"🔍 Tentando mapear por username: {winner_username}")
                if p_white and p_white.get('lichess_username') == winner_username:
                    winner_id = p_white['discord_id']
                    loser_id = p_black['discord_id'] if p_black else (challenged_id if winner_id == challenger_id else challenger_id)
                    logger.info(f"✅ Mapeado por username: Winner={winner_id} (white), Loser={loser_id}")
                elif p_black and p_black.get('lichess_username') == winner_username:
                    winner_id = p_black['discord_id']
                    loser_id = p_white['discord_id'] if p_white else (challenger_id if winner_id == challenged_id else challenged_id)
                    logger.info(f"✅ Mapeado por username: Winner={winner_id} (black), Loser={loser_id}")

            # Método 1: Mapear por cor das peças (mais confiável)
            if winner_color:
                logger.info(f"🔍 Tentando mapear por cor: {winner_color}")
                if winner_color == 'white' and p_white:
                    winner_id = p_white['discord_id']
                    loser_id = p_black['discord_id'] if p_black else (challenged_id if winner_id == challenger_id else challenger_id)
                    logger.info(f"✅ Mapeado por cor: Winner={winner_id} (white), Loser={loser_id}")
                elif winner_color == 'black' and p_black:
                    winner_id = p_black['discord_id']
                    loser_id = p_white['discord_id'] if p_white else (challenger_id if winner_id == challenged_id else challenged_id)
                    logger.info(f"✅ Mapeado por cor: Winner={winner_id} (black), Loser={loser_id}")
                else:
                    logger.warning(f"⚠️ winner_color={winner_color} mas player correspondente não encontrado no banco")
            else:
                logger.warning(f"⚠️ winner_color não definido no outcome")

            # Método 3: Fallback baseado na lógica do desafio (challenger vs challenged)
            if not winner_id:
                logger.warning(f"⚠️ Não foi possível mapear vencedor para desafio {ch['id']}. Usando fallback baseado no desafio.")
                logger.warning(f"   Challenger: {challenger_id}, Challenged: {challenged_id}")
                logger.warning(f"   Winner color: {winner_color}, Winner username: {winner_username}")
                logger.warning(f"   Players: White discord_id={p_white['discord_id'] if p_white else None}, Black discord_id={p_black['discord_id'] if p_black else None}")

                # Determina vencedor baseado na cor e quem desafiou
                if winner_color == 'white':
                    # Verifica se challenger estava nas brancas
                    if p_white and p_white['discord_id'] == challenger_id:
                        winner_id = challenger_id
                        loser_id = challenged_id
                    elif p_black and p_black['discord_id'] == challenger_id:
                        # Challenger estava nas pretas, então challenged venceu (brancas)
                        winner_id = challenged_id
                        loser_id = challenger_id
                    else:
                        # Fallback: assume challenger venceu
                        winner_id = challenger_id
                        loser_id = challenged_id
                elif winner_color == 'black':
                    # Verifica se challenger estava nas pretas
                    if p_black and p_black['discord_id'] == challenger_id:
                        winner_id = challenger_id
                        loser_id = challenged_id
                    elif p_white and p_white['discord_id'] == challenger_id:
                        # Challenger estava nas brancas, então challenged venceu (pretas)
                        winner_id = challenged_id
                        loser_id = challenger_id
                    else:
                        # Fallback: assume challenger venceu
                        winner_id = challenger_id
                        loser_id = challenged_id
                else:
                    # Sem cor definida, usa challenger como vencedor
                    winner_id = challenger_id
                    loser_id = challenged_id

                logger.warning(f"⚠️ Fallback usado: Winner={winner_id}, Loser={loser_id}")

            # Garante que temos um loser_id
            if winner_id and not loser_id:
                loser_id = challenged_id if winner_id == challenger_id else challenger_id

            # Se ainda não temos winner_id, usa fallback simples
            if not winner_id:
                logger.error(f"❌ Impossível determinar vencedor para desafio {ch['id']}. Usando challenger como vencedor.")
                winner_id = challenger_id
                loser_id = challenged_id

            result = 'win'
            logger.info(f"🏆 Resultado final: winner_id={winner_id} ({'challenger' if winner_id == challenger_id else 'challenged'}), loser_id={loser_id} ({'challenger' if loser_id == challenger_id else 'challenged'})")
            logger.info(f"🏆 Challenger: {challenger_id}, Challenged: {challenged_id}")

        # Persist result with anonymous-account handling
        # Determine linked status for white/black (players linked to our DB)
        linked_white = bool(p_white)
        linked_black = bool(p_black)

        if not linked_white and not linked_black:
            # Both anonymous: still record winner/loser for display purposes
            await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
            await database.update_challenge_status(ch['id'], 'finished')
            logger.info(f"Desafio {ch['id']} marcado como finalizado (ambos anônimos — sem atualização de stats/ratings)")
            skip_stats_update = True
        else:
            # If only one player is linked, register the linked player as the winner regardless of actual outcome
            if linked_white and not linked_black:
                linked_player = p_white['discord_id']
                other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                winner_id = linked_player
                loser_id = other_player
                result = 'win'
                await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                await database.update_challenge_status(ch['id'], 'finished')
                logger.info(f"Desafio {ch['id']} marcado como finalizado (um anônimo presente) — vencedor registrado: {winner_id}")
                skip_stats_update = False
            elif linked_black and not linked_white:
                linked_player = p_black['discord_id']
                other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                winner_id = linked_player
                loser_id = other_player
                result = 'win'
                await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                await database.update_challenge_status(ch['id'], 'finished')
                logger.info(f"Desafio {ch['id']} marcado como finalizado (um anônimo presente) — vencedor registrado: {winner_id}")
                skip_stats_update = False
            else:
                # Both linked — record the actual outcome
                await database.mark_challenge_as_finished(ch['id'], winner_id, loser_id, result, outcome.get('pgn') or ch.get('game_url'))
                await database.update_challenge_status(ch['id'], 'finished')
                logger.info(f"Desafio {ch['id']} marcado como finalizado")
                skip_stats_update = False

        # Update internal stats/ratings
        try:
            if skip_stats_update:
                pass
            else:
                if result == 'win' and winner_id and loser_id:
                    if p_white and not p_black:
                        linked_player = p_white['discord_id']
                        other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                        await database.update_player_stats(linked_player, mode, 'win')
                        await database.update_player_stats(other_player, mode, 'loss')
                        logger.info(f"Estatísticas atualizadas (um anônimo presente): {linked_player} (win), {other_player} (loss)")
                        await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                        if is_rated:
                            rating_changes = await database.apply_match_ratings(linked_player, other_player, mode)
                            if rating_changes:
                                logger.info(f"Ratings atualizados para desafio {ch['id']} (um anônimo presente)")
                                await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                    elif p_black and not p_white:
                        linked_player = p_black['discord_id']
                        other_player = challenger_id if str(challenger_id) != str(linked_player) else challenged_id
                        await database.update_player_stats(linked_player, mode, 'win')
                        await database.update_player_stats(other_player, mode, 'loss')
                        logger.info(f"Estatísticas atualizadas (um anônimo presente): {linked_player} (win), {other_player} (loss)")
                        await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                        if is_rated:
                            rating_changes = await database.apply_match_ratings(linked_player, other_player, mode)
                            if rating_changes:
                                logger.info(f"Ratings atualizados para desafio {ch['id']} (um anônimo presente)")
                                await database.check_and_unlock_achievements(linked_player, mode, 'win', other_player)
                    else:
                        # Both linked — standard flow
                        await database.update_player_stats(winner_id, mode, 'win')
                        await database.update_player_stats(loser_id, mode, 'loss')
                        logger.info(f"Estatísticas atualizadas: {winner_id} (win), {loser_id} (loss)")

                        await database.check_and_unlock_achievements(winner_id, mode, 'win', loser_id)
                        await database.check_and_unlock_achievements(loser_id, mode, 'loss', winner_id)

                        if is_rated:
                            rating_changes = await database.apply_match_ratings(winner_id, loser_id, mode)
                            if rating_changes:
                                logger.info(f"Ratings atualizados para desafio {ch['id']}")
                                await database.check_and_unlock_achievements(winner_id, mode, 'win', loser_id)
                                await database.check_and_unlock_achievements(loser_id, mode, 'loss', winner_id)
                                try:
                                    from cogs.rankings import Rankings
                                    rankings_cog = bot.get_cog('Rankings')
                                    if rankings_cog:
                                        await rankings_cog.update_fixed_ranking()
                                except Exception as e:
                                    logger.error(f"Erro ao atualizar ranking fixo para desafio {ch['id']}: {e}")
                elif result == 'draw':
                    # In draw, credit draw to linked participants
                    if p_white and p_white.get('discord_id'):
                        await database.update_player_stats(p_white['discord_id'], mode, 'draw')
                    if p_black and p_black.get('discord_id'):
                        await database.update_player_stats(p_black['discord_id'], mode, 'draw')
                    logger.info(f"Estatísticas atualizadas (empate): {p_white['discord_id'] if p_white else 'anon'}, {p_black['discord_id'] if p_black else 'anon'}")

                    if is_rated and p_white and p_black:
                        rating_changes = await database.apply_draw_ratings(p_white['discord_id'], p_black['discord_id'], mode)
                        if rating_changes:
                            logger.info(f"Ratings atualizados (empate) para desafio {ch['id']}")
        except Exception as e:
            logger.error(f"Failed to update stats/ratings for challenge {ch['id']}: {e}", exc_info=True)

        # Salvar partida no histórico
        try:
            p1_id, p2_id = (challenger_id, challenged_id)
            p1 = await database.get_all_player_stats(p1_id)
            p2 = await database.get_all_player_stats(p2_id)
            p1_name = p1.get('discord_username') if p1 else 'Unknown'
            p2_name = p2.get('discord_username') if p2 else 'Unknown'

            p1_rating_before, p2_rating_before = (None, None)
            p1_rating_after, p2_rating_after = (None, None)

            if rating_changes:
                if result == 'win':
                    winner_data = rating_changes.get('winner', {})
                    loser_data = rating_changes.get('loser', {})
                    if winner_id == p1_id:
                        p1_rating_before = winner_data.get('old_rating')
                        p1_rating_after = winner_data.get('new_rating')
                        p2_rating_before = loser_data.get('old_rating')
                        p2_rating_after = loser_data.get('new_rating')
                    else:
                        p1_rating_before = loser_data.get('old_rating')
                        p1_rating_after = loser_data.get('new_rating')
                        p2_rating_before = winner_data.get('old_rating')
                        p2_rating_after = winner_data.get('new_rating')
                elif result == 'draw':
                    p1_data = rating_changes.get('player1', {})
                    p2_data = rating_changes.get('player2', {})
                    p1_rating_before = p1_data.get('old')
                    p1_rating_after = p1_data.get('new')
                    p2_rating_before = p2_data.get('old')
                    p2_rating_after = p2_data.get('new')

            await database.save_game_history(
                player1_id=p1_id,
                player2_id=p2_id,
                player1_name=p1_name,
                player2_name=p2_name,
                winner_id=winner_id,
                result=result,
                mode=mode,
                time_control=ch.get('time_control'),
                game_url=game_url,
                p1_rating_before=p1_rating_before,
                p2_rating_before=p2_rating_before,
                p1_rating_after=p1_rating_after,
                p2_rating_after=p2_rating_after,
            )
            logger.info(f"Partida salva no histórico para desafio {ch['id']}")
        except Exception as e:
            logger.error(f"Erro ao salvar partida no histórico para desafio {ch['id']}: {e}", exc_info=True)


        # Announce result to channel
        try:
            channel_id = ch.get('channel_id')
            if channel_id:
                try:
                    channel_id_int = int(channel_id)
                    channel = await bot.fetch_channel(channel_id_int)
                except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException):
                    logger.warning(f"Canal {channel_id} não encontrado ou inválido para desafio {ch['id']}")
                    channel = None
                except Exception as e:
                    logger.error(f"Erro ao buscar canal {channel_id} para desafio {ch['id']}: {e}")
                    channel = None

                if channel:
                    logger.info(f"📢 Anunciando resultado no canal {channel_id} para desafio {ch['id']}")

                    # Criar embeds usando a função auxiliar
                    logger.info(f"📊 Rating changes para canal: {rating_changes}")
                    embeds_to_send = await create_result_embeds(bot, ch, outcome, winner_id, loser_id, result, rating_changes, p_white, p_black)

                    # Enviar todos os embeds
                    await channel.send(embeds=embeds_to_send)

                    # Resultados são mostrados apenas no canal, não em DM

                    if result == 'draw':
                        logger.info(f"📊 Anunciando empate para desafio {ch['id']}")
                    else:
                        logger.info(f"🏆 Anunciando vitória para desafio {ch['id']}: {winner_id} vs {loser_id}")
                    logger.info(f"✅ Resultado anunciado com sucesso no canal {channel_id} para desafio {ch['id']}")
                else:
                    logger.warning(f"Canal {channel_id} não encontrado ou inválido para desafio {ch['id']}")
            else:
                logger.warning(f"Canal {channel_id} não encontrado ou inválido para desafio {ch['id']}")
        except Exception as e:
            logger.error(f"Failed to announce result for challenge {ch['id']}: {e}", exc_info=True)

        return True, rating_changes  # Processed successfully

    except Exception as e:
        logger.error(f"Erro ao processar desafio {ch['id']}: {e}", exc_info=True)
        return False, None


# ==============================================================================
# --- FUNÇÕES PARA PARTIDAS PROGRAMADAS ---
# ==============================================================================

async def check_scheduled_challenges(bot):
    """Verifica desafios agendados próximos e envia lembretes ou ativa desafios."""
    try:
        # Buscar desafios agendados que estão prontos para ativação
        ready_challenges = await database.get_scheduled_challenges_ready()
        
        logger.info(f"🔍 Encontrados {len(ready_challenges)} desafios prontos para ativação")
        
        for challenge in ready_challenges:
            logger.info(f"🎯 Ativando desafio ID {challenge['id']} agendado para {challenge['scheduled_at']}")
            await start_scheduled_challenge(bot, challenge)
                
    except Exception as e:
        logger.error(f"Erro ao verificar lembretes de desafios agendados: {e}")

async def start_scheduled_challenge(bot, challenge):
    """Ativa um desafio agendado criando a partida no Lichess."""
    try:
        logger.info(f"🎯 Iniciando ativação do desafio {challenge['id']}")
        # Criar partida no Lichess
        game_url = await lichess_api.create_lichess_game(challenge['time_control'], rated=False)
        
        if game_url:
            logger.info(f"✅ Partida criada: {game_url}")
            await database.update_challenge_game_url(challenge['id'], game_url)
            await database.activate_scheduled_challenge(challenge['id'])
            
            # Buscar usuários
            player1 = await bot.fetch_user(int(challenge['challenger_id']))
            player2 = await bot.fetch_user(int(challenge['challenged_id']))
            
            # Enviar DM com link da partida
            embed = discord.Embed(
                title="🎯 ➜ Desafio Agendado Ativado!",
                description="Seu desafio agendado foi ativado e está pronto para jogar!",
                color=0xCD0000
            )
            embed.add_field(
                name="Detalhes:",
                value=f"🎯 ➜ **Oponente:** {player2.mention if challenge['challenger_id'] == str(player1.id) else player1.mention}\n"
                      f"⏱️ ➜ **Tempo:** {challenge['time_control']}\n"
                      f"🏆 ➜ **Rating:** {'Sim' if challenge.get('is_rated', False) else 'Não'}\n"
                      f"🔗 ➜ **Partida:** [Clique aqui]({game_url})",
                inline=False
            )
            embed.set_footer(text="Quando a partida terminar, clique no botão 'Finalizar' para processar o resultado.")
            
            # Importar a view de finalização
            from cogs.chess import GameFinishView
            
            # Cria a view com o botão de finalização
            view_player1 = GameFinishView(bot, challenge['id'])
            view_player2 = GameFinishView(bot, challenge['id'])
            
            try:
                dm_message = await player1.send(embed=embed, view=view_player1)
                view_player1.message = dm_message
            except discord.Forbidden:
                pass
                
            try:
                dm_message = await player2.send(embed=embed, view=view_player2)
                view_player2.message = dm_message
            except discord.Forbidden:
                pass
            
            logger.info(f"🎯 Desafio agendado #{challenge['id']} ativado")
        
    except Exception as e:
        logger.error(f"Erro ao ativar desafio agendado #{challenge['id']}: {e}")

# ==============================================================================
# --- TAREFAS EM SEGUNDO PLANO ---
# ==============================================================================

# Tarefa para verificar partidas finalizadas
@tasks.loop(minutes=2)
async def check_games_loop():
    # Processamento automático de partidas finalizadas
    await check_finished_games()
    # Limpar jogos inválidos a cada 10 execuções (20 minutos)
    if check_games_loop.current_loop % 10 == 0:
        await cleanup_invalid_games()

async def get_next_scheduled_challenge_time():
    """Retorna o datetime do próximo desafio agendado futuro, ou None se não houver."""
    def _query():
        conn = database.get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, scheduled_at 
            FROM challenges 
            WHERE status = 'scheduled' 
            AND datetime(scheduled_at) > datetime('now')
            ORDER BY scheduled_at ASC 
            LIMIT 1
        """)
        result = cursor.fetchone()
        conn.close()
        return result
    
    result = await asyncio.to_thread(_query)
    logger.info(f"🔍 Query result: {result}")
    if result:
        logger.info(f"📅 Próximo desafio encontrado: ID {result['id']} agendado para {result['scheduled_at']}")
        # Converter string para datetime - tentar múltiplos formatos
        try:
            # Primeiro tentar formato ISO (com T)
            dt = datetime.fromisoformat(result['scheduled_at'])
            logger.info(f"📅 Data convertida (ISO): {dt}")
            return dt
        except ValueError:
            try:
                # Se falhar, tentar formato SQL (sem T)
                dt = datetime.strptime(result['scheduled_at'], '%Y-%m-%d %H:%M:%S')
                logger.info(f"📅 Data convertida (SQL): {dt}")
                return dt
            except ValueError as e:
                logger.error(f"Erro ao converter data {result['scheduled_at']}: {e}")
                return None
    logger.info("📅 Nenhum desafio agendado encontrado")
    return None

# Tarefa para desafios agendados - executa exatamente no horário
async def scheduled_challenges_loop():
    """Loop que verifica desafios agendados exatamente no horário marcado."""
    logger.info("🎯 Iniciando loop de desafios agendados")
    
    # Primeiro, verificar se há desafios atrasados ao iniciar
    logger.info("🔍 Verificando desafios atrasados na inicialização...")
    if _monitor_instance and _monitor_instance.bot:
        try:
            ready_challenges = await database.get_scheduled_challenges_ready()
            if ready_challenges:
                logger.info(f"⚠️ Encontrados {len(ready_challenges)} desafios atrasados, ativando...")
                for challenge in ready_challenges:
                    logger.info(f"🎯 Ativando desafio atrasado ID {challenge['id']}")
                    await start_scheduled_challenge(_monitor_instance.bot, challenge)
            else:
                logger.info("✅ Nenhum desafio atrasado encontrado")
        except Exception as e:
            logger.error(f"Erro ao verificar desafios atrasados: {e}")
    
    while True:
        try:
            logger.info("🔄 Iniciando nova iteração do loop de desafios agendados")
            # Calcular tempo até o próximo desafio agendado
            next_challenge_time = await get_next_scheduled_challenge_time()
            
            if next_challenge_time:
                # Calcular quanto tempo até o próximo desafio
                now = datetime.now()
                wait_seconds = (next_challenge_time - now).total_seconds()
                
                logger.info(f"⏰ Agora: {now}, Próximo desafio: {next_challenge_time}, Segundos para esperar: {wait_seconds}")
                
                if wait_seconds > 0:
                    logger.info(f"⏰ Aguardando {wait_seconds:.1f} segundos até o próximo desafio")
                    await asyncio.sleep(wait_seconds)
                else:
                    logger.warning(f"⚠️ Desafio atrasado! Wait_seconds negativo: {wait_seconds}, verificando novamente...")
                    await asyncio.sleep(1)  # Pequena pausa
                    continue
                
                # Verificar desafios prontos
                logger.info("🔍 Verificando desafios prontos para ativação")
                if _monitor_instance and _monitor_instance.bot:
                    await check_scheduled_challenges(_monitor_instance.bot)
                else:
                    logger.warning("Bot instance not available for scheduled challenges check")
            else:
                # Nenhum desafio agendado, aguardar 5 minutos e verificar novamente
                logger.info("📅 Nenhum desafio agendado encontrado, verificando novamente em 5 minutos")
                await asyncio.sleep(300)  # 5 minutos
                
        except Exception as e:
            logger.error(f"Erro no loop de desafios agendados: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            await asyncio.sleep(60)  # Em caso de erro, aguardar 1 minuto

async def start_background_tasks():
    """Inicia todas as tarefas em segundo plano."""
    global _scheduled_challenges_task
    
    if _monitor_instance is None:
        logger.warning("⚠️ Challenge monitor ainda não foi configurado. Chame set_bot_instance(bot) antes de iniciar.")
        return
    logger.info("Iniciando monitor de partidas via start_background_tasks()...")
    _monitor_instance.start()

    # Iniciar tarefas adicionais
    check_games_loop.start()
    # Iniciar o loop de desafios agendados como uma tarefa separada
    logger.info("🎯 Iniciando loop de desafios agendados...")
    try:
        _scheduled_challenges_task = asyncio.create_task(scheduled_challenges_loop())
        logger.info(f"🎯 Task de desafios agendados criada: {_scheduled_challenges_task}")
    except Exception as e:
        logger.error(f"Erro ao criar task de desafios agendados: {e}")

    logger.info("✅ Tarefas em segundo plano iniciadas!")

async def stop_background_tasks():
    """Para todas as tarefas em segundo plano adequadamente."""
    global _scheduled_challenges_task
    
    logger.info("🛑 Parando tarefas em segundo plano...")
    
    # Parar o loop de verificação de jogos
    if check_games_loop.is_running():
        check_games_loop.stop()
        logger.info("✅ Loop de verificação de jogos parado")
    
    # Cancelar a tarefa do monitor de desafios
    if _monitor_instance and _monitor_instance.task and not _monitor_instance.task.done():
        _monitor_instance.task.cancel()
        try:
            await _monitor_instance.task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Monitor de desafios parado")
    
    # Cancelar a tarefa de desafios agendados
    if _scheduled_challenges_task and not _scheduled_challenges_task.done():
        _scheduled_challenges_task.cancel()
        try:
            await _scheduled_challenges_task
        except asyncio.CancelledError:
            pass
        logger.info("✅ Loop de desafios agendados parado")
    
    logger.info("✅ Todas as tarefas em segundo plano foram paradas")
