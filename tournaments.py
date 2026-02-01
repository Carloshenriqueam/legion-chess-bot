from discord.ext import commands
import discord
from discord import app_commands
from discord.ui import View, Button
import logging
import database
import asyncio
from typing import Literal

logger = logging.getLogger(__name__)


def get_mode_from_time_control(time_control: str) -> str:
    """Determina o modo (bullet/blitz/rapid) baseado no time control."""
    try:
        # time_control vem no formato "minutos+incremento" (ex: "5+0", "10+5")
        total_time = int(time_control.split('+')[0])

        if total_time <= 2:
            return "bullet"  # 1+0, 1+1, 2+1
        elif total_time <= 5:
            return "blitz"   # 3+0, 3+2, 5+0
        else:
            return "rapid"   # 10+0, 15+10, 30+0
    except:
        return "blitz"  # default fallback


async def get_player_rating(discord_id: str, mode: str) -> int:
    """Busca o rating de um jogador para um modo específico."""
    try:
        player_stats = await database.get_all_player_stats(discord_id)
        if player_stats:
            rating_key = f"rating_{mode}"
            return player_stats.get(rating_key, 1200)  # default 1200 se não encontrar
        return 1200  # default para jogadores não registrados
    except Exception as e:
        logger.warning(f"Erro ao buscar rating para {discord_id}: {e}")
        return 1200


async def format_participants_list(bot, participants, mode: str, limit: int = 10) -> list:
    """Formata lista de participantes ordenada por rating (maior para menor)."""
    if not participants:
        return ["Nenhum participante ainda"]

    # Busca ratings e prepara dados
    participant_data = []
    for p in participants:
        try:
            user = await bot.fetch_user(int(p['player_id']))
            display_name = user.display_name
        except:
            display_name = p.get('discord_username', 'Usuário desconhecido')

        rating = await get_player_rating(p['player_id'], mode)
        participant_data.append({
            'name': display_name,
            'rating': rating,
            'id': p['player_id']  # Para desempate por ordem de chegada
        })

    # Ordena por rating decrescente, depois por ID crescente (ordem de chegada)
    participant_data.sort(key=lambda x: (-x['rating'], x['id']))

    # Cria lista numerada
    participants_list = []
    for i, data in enumerate(participant_data[:limit], 1):
        participants_list.append(f"{i}. {data['name']} ({data['rating']})")

    if len(participants) > limit:
        participants_list.append(f"... e mais {len(participants) - limit} participantes")

    return participants_list


async def format_swiss_standings(bot, tournament_id: int, limit: int = 10) -> str:
    """Formata a tabela de classificação do torneio suíço."""
    try:
        standings = await database.get_swiss_standings(tournament_id)
        if not standings:
            return "Nenhuma classificação disponível ainda."

        # Formatar cada linha da classificação
        standings_lines = []
        for i, player in enumerate(standings[:limit], 1):
            try:
                user = await bot.fetch_user(int(player['discord_id']))
                display_name = user.display_name
            except:
                display_name = player.get('discord_username', 'Usuário desconhecido')

            points = player.get('points', 0)
            wins = player.get('wins', 0)
            draws = player.get('draws', 0)
            losses = player.get('losses', 0)
            tiebreak = player.get('tiebreak_score', 0)

            line = f"{i}. {display_name} - {points}pts ({wins}V/{draws}E/{losses}D)"
            if tiebreak > 0:
                line += f" | TB: {tiebreak}"
            standings_lines.append(line)

        if len(standings) > limit:
            standings_lines.append(f"... e mais {len(standings) - limit} jogadores")

        return "\n".join(standings_lines)
    except Exception as e:
        logger.error(f"Erro ao formatar classificação suíça: {e}")
        return "Erro ao carregar classificação."


async def notify_swiss_pairings(bot, tournament_id: int, round_number: int):
    """Envia DMs para jogadores notificando sobre seus pairings na rodada."""
    try:
        # Busca informações do torneio
        tournament = await database.get_swiss_tournament(tournament_id)
        if not tournament:
            return

        # Busca pairings da rodada
        pairings = await database.get_swiss_pairings_for_round(tournament_id, round_number)
        if not pairings:
            return

        # Determinar modo baseado no time_control
        time_control_str = tournament.get('time_control', '10+0')
        try:
            total_time = int(time_control_str.split('+')[0])
            if total_time <= 2:
                mode = "Bullet"
            elif total_time <= 5:
                mode = "Blitz"
            else:
                mode = "Rapid"
        except:
            mode = "Rapid"

        # Determina se a próxima rodada é a última para marcar o título
        try:
            total_rounds = int(tournament.get('nb_rounds', 1))
        except Exception:
            total_rounds = 1

        last_marker = " (ULTIMA RODADA)" if round_number == total_rounds else ""

        # Para cada pairing, notifica ambos os jogadores
        for pairing in pairings:
            # Caso de bye: jogador 2 é None -> o jogador 1 recebe 1 ponto automaticamente
            if pairing.get('player2_id') is None:
                try:
                    player1 = await bot.fetch_user(int(pairing['player1_id']))
                    if player1:
                        embed = discord.Embed(
                            title=f"Torneio Suíço ({tournament['name']}) - Rodada {round_number}{last_marker}",
                            description=(f"Você não foi pareado nesta rodada (bye).\n"
                                         "Você receberá +1 ponto por não ter sido pareado e ficará aguardando a próxima rodada."),
                            color=discord.Color.orange()
                        )

                        embed.add_field(
                            name="Detalhes",
                            value=f"**Rodada:** {round_number}\n**Recompensa:** +1 ponto (bye)",
                            inline=False
                        )

                        embed.set_footer(text="Aguarde a próxima rodada. Boa sorte!")

                        try:
                            await player1.send(embed=embed)
                            logger.info(f"DM de bye enviada para {player1.name} (pairing {pairing.get('id')})")
                        except discord.Forbidden:
                            logger.warning(f"Não foi possível enviar DM de bye para jogador {pairing.get('player1_id')} (DMs desabilitadas)")
                        except Exception as e:
                            logger.error(f"Erro ao enviar DM de bye para jogador {pairing.get('player1_id')}: {e}")

                        # Atualiza as estatísticas do perfil: contabiliza um 'win' para o jogador que recebeu bye
                        try:
                            mode_key = mode.lower() if isinstance(mode, str) else 'rapid'
                            await database.update_player_stats(str(pairing.get('player1_id')), mode_key, 'win')
                        except Exception as e:
                            logger.warning(f"Erro ao atualizar estatísticas (bye) para jogador {pairing.get('player1_id')}: {e}")

                        # Também publica no canal do torneio se houver channel_id
                        try:
                            channel_id = tournament.get('channel_id')
                            if channel_id:
                                try:
                                    channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
                                except Exception:
                                    channel = None

                                if channel:
                                    try:
                                        public_embed = discord.Embed(
                                            title=f"Torneio Suíço ({tournament['name']}) - Rodada {round_number}{last_marker}",
                                            description=(f"<@{pairing.get('player1_id')}> não foi pareado nesta rodada e recebeu +1 ponto (bye)."),
                                            color=discord.Color.orange()
                                        )
                                        public_embed.add_field(name="Rodada", value=str(round_number), inline=True)
                                        await channel.send(embed=public_embed)
                                    except Exception as e:
                                        logger.warning(f"Não foi possível enviar anúncio de bye no canal do torneio: {e}")
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"Erro ao processar bye para pairing {pairing.get('id')}: {e}")

                # continue para o próximo pairing
                continue

            # Pareamentos normais
            if not pairing.get('player1_id') or not pairing.get('player2_id'):
                logger.warning(f"Pairing {pairing.get('id')} tem jogador(es) None, pulando...")
                continue
            
            try:
                # Notifica jogador 1
                player1 = await bot.fetch_user(int(pairing['player1_id']))
                if player1:
                    # Busca nome do oponente
                    try:
                        player2 = await bot.fetch_user(int(pairing['player2_id']))
                        opponent_name = player2.display_name if player2 else pairing.get('player2_name', 'Desconhecido')
                    except:
                        opponent_name = pairing.get('player2_name', 'Desconhecido')

                    # Criar embed no formato especificado
                    embed = discord.Embed(
                        title=f"Torneio Suíço ({tournament['name']}) - Rodada {round_number}{last_marker}",
                        description=f"Você foi pareado contra {opponent_name}!",
                        color=discord.Color.blue()
                    )

                    embed.add_field(
                        name="Detalhes da Partida",
                        value=f"**Oponente:** {opponent_name}\n**Rodada:** {round_number}\n**Modo:** {mode}",
                        inline=False
                    )

                    embed.add_field(
                        name="Ação Necessária",
                        value="Clique no botão abaixo para aceitar a partida e iniciar a partida!",
                        inline=False
                    )

                    # Criar view com botão de aceitar
                    view = AcceptSwissGameView(
                        bot=bot,
                        tournament_id=tournament_id,
                        pairing_id=pairing['id'],
                        player1_id=pairing['player1_id'],
                        player2_id=pairing['player2_id'],
                        round_number=round_number
                    )

                    await player1.send(embed=embed, view=view)
                    logger.info(f"DM enviada para {player1.name} sobre pairing na rodada {round_number}")

            except discord.Forbidden:
                logger.warning(f"Não foi possível enviar DM para jogador {pairing['player1_id']} (DMs desabilitadas)")
            except Exception as e:
                logger.error(f"Erro ao enviar DM para jogador {pairing['player1_id']}: {e}")

            try:
                # Notifica jogador 2
                player2 = await bot.fetch_user(int(pairing['player2_id']))
                if player2:
                    # Busca nome do oponente
                    try:
                        player1 = await bot.fetch_user(int(pairing['player1_id']))
                        opponent_name = player1.display_name if player1 else pairing.get('player1_name', 'Desconhecido')
                    except:
                        opponent_name = pairing.get('player1_name', 'Desconhecido')

                    # Criar embed no formato especificado
                    embed = discord.Embed(
                        title=f"Torneio Suíço ({tournament['name']}) - Rodada {round_number}{last_marker}",
                        description=f"Você foi pareado contra {opponent_name}!",
                        color=discord.Color.blue()
                    )

                    embed.add_field(
                        name="Detalhes da Partida",
                        value=f"**Oponente:** {opponent_name}\n**Rodada:** {round_number}\n**Modo:** {mode}",
                        inline=False
                    )

                    embed.add_field(
                        name="Ação Necessária",
                        value="Clique no botão abaixo para aceitar a partida e iniciar a partida!",
                        inline=False
                    )

                    # Criar view com botão de aceitar
                    view = AcceptSwissGameView(
                        bot=bot,
                        tournament_id=tournament_id,
                        pairing_id=pairing['id'],
                        player1_id=pairing['player1_id'],
                        player2_id=pairing['player2_id'],
                        round_number=round_number
                    )

                    await player2.send(embed=embed, view=view)
                    logger.info(f"DM enviada para {player2.name} sobre pairing na rodada {round_number}")

            except discord.Forbidden:
                logger.warning(f"Não foi possível enviar DM para jogador {pairing['player2_id']} (DMs desabilitadas)")
            except Exception as e:
                logger.error(f"Erro ao enviar DM para jogador {pairing['player2_id']}: {e}")

    except Exception as e:
        logger.error(f"Erro ao notificar pairings suíços: {e}")


async def handle_swiss_round_completion(bot, tournament_id: int, current_round: int):
    """Gerencia o intervalo entre rodadas e geração automática da próxima rodada."""
    try:
        tournament = await database.get_swiss_tournament(tournament_id)
        if not tournament:
            return
        
        participants = await database.get_swiss_tournament_participants(tournament_id)
        if not participants:
            return
        
        nb_rounds = tournament.get('nb_rounds', 1)
        
        if current_round >= nb_rounds:
            await announce_swiss_tournament_winner(bot, tournament_id, tournament)
            return
        
        next_round = current_round + 1
        
        standings = await database.get_swiss_standings(tournament_id)
        embed_interval = discord.Embed(
            title=f"⏱️ {tournament['name']}",
            description=f"Rodada {current_round} finalizada!\n\n**Próxima rodada em 1 minuto...**",
            color=discord.Color.orange()
        )
        
        standings_lines = []
        for i, player in enumerate(standings[:5], 1):
            try:
                user = await bot.fetch_user(int(player['player_id']))
                display_name = user.display_name if user else player.get('discord_username', 'Desconhecido')
            except:
                display_name = player.get('discord_username', 'Desconhecido')
            
            points = player.get('points', 0)
            wins = player.get('wins', 0)
            draws = player.get('draws', 0)
            losses = player.get('losses', 0)
            
            line = f"{i}. {display_name} - {points}pts ({wins}V/{draws}E/{losses}D)"
            standings_lines.append(line)
        
        embed_interval.add_field(
            name="📊 Classificação Atual",
            value="\n".join(standings_lines) if standings_lines else "Sem dados",
            inline=False
        )
        
        try:
            for participant in participants:
                if not participant.get('player_id'):
                    continue
                try:
                    user = await bot.fetch_user(int(participant['player_id']))
                    if user:
                        await user.send(embed=embed_interval)
                except Exception as e:
                    logger.warning(f"Não foi possível enviar intervalo para participante {participant.get('discord_username')}: {e}")
        except Exception as e:
            logger.warning(f"Erro ao enviar embeds de intervalo: {e}")
        
        await asyncio.sleep(60)
        
        success, pairings = await database.generate_and_save_swiss_round(tournament_id, next_round)
        if success:
            await notify_swiss_pairings(bot, tournament_id, next_round)
            logger.info(f"Torneio {tournament_id}: Rodada {next_round} gerada após intervalo")
        else:
            logger.error(f"Erro ao gerar rodada {next_round} para torneio {tournament_id}: {pairings}")
    
    except Exception as e:
        logger.error(f"Erro ao gerenciar conclusão de rodada: {e}")


async def announce_swiss_tournament_winner(bot, tournament_id: int, tournament):
    """Anuncia o vencedor do torneio suíço com podio top 3."""
    try:
        standings = await database.get_swiss_standings(tournament_id)
        if not standings or len(standings) < 1:
            logger.warning(f"Torneio {tournament_id}: Sem participantes na classificação final")
            return
        
        participants = await database.get_swiss_tournament_participants(tournament_id)
        
        medals = ["🥇", "🥈", "🥉"]
        podio_lines = []
        
        for i in range(min(3, len(standings))):
            try:
                player = standings[i]
                user = await bot.fetch_user(int(player['player_id']))
                display_name = user.display_name if user else player.get('discord_username', 'Desconhecido')
            except:
                player = standings[i]
                display_name = player.get('discord_username', 'Desconhecido')
            
            points = player.get('points', 0)
            wins = player.get('wins', 0)
            draws = player.get('draws', 0)
            losses = player.get('losses', 0)
            
            medal = medals[i] if i < len(medals) else f"#{i+1}"
            line = f"{medal} **{display_name}** - {points}pts ({wins}V/{draws}E/{losses}D)"
            podio_lines.append(line)
        
        embed_winner = discord.Embed(
            title=f"🏆 {tournament['name']} - TORNEIO FINALIZADO!",
            description="Parabéns aos vencedores!",
            color=discord.Color.gold()
        )
        
        # Adiciona a conquista para o vencedor (Top 1)
        if standings:
            winner_player = standings[0]
            winner_id = winner_player.get('player_id')
            if winner_id:
                achievement_name = f"Vencedor do Torneio: {tournament['name']}"
                achievement_description = f"Campeão do torneio suíço '{tournament['name']}'!"
                await database.add_achievement(winner_id, achievement_name, achievement_description, "🥇")

        embed_winner.add_field(
            title=f"🏆 {tournament['name']} - TORNEIO FINALIZADO!",
            description="Parabéns ao vencedor!",
            color=discord.Color.gold()
        )
        
        embed_winner.add_field(
            name="🎯 Podio Final",
            value="\n".join(podio_lines),
            inline=False
        )
        
        final_standings_lines = []
        for i, player in enumerate(standings, 1):
            try:
                user = await bot.fetch_user(int(player['player_id']))
                display_name = user.display_name if user else player.get('discord_username', 'Desconhecido')
            except:
                display_name = player.get('discord_username', 'Desconhecido')
            
            points = player.get('points', 0)
            wins = player.get('wins', 0)
            draws = player.get('draws', 0)
            losses = player.get('losses', 0)
            
            line = f"{i}. {display_name} - {points}pts ({wins}V/{draws}E/{losses}D)"
            final_standings_lines.append(line)
        
        embed_winner.add_field(
            name="📊 Classificação Final",
            value="\n".join(final_standings_lines) if final_standings_lines else "Sem dados",
            inline=False
        )
        
        try:
            for participant in participants:
                if not participant.get('player_id'):
                    continue
                try:
                    user = await bot.fetch_user(int(participant['player_id']))
                    if user:
                        await user.send(embed=embed_winner)
                except Exception as e:
                    logger.warning(f"Não foi possível enviar resultado final para participante {participant.get('discord_username')}: {e}")
        except Exception as e:
            logger.warning(f"Erro ao enviar embeds de vencedor: {e}")

        # Enviar resultado final também no canal onde o torneio foi criado
        try:
            channel_id = tournament.get('channel_id')
            if channel_id:
                try:
                    channel = await bot.fetch_channel(int(channel_id))
                    if channel:
                        await channel.send(embed=embed_winner)
                        logger.info(f"Resultado final do torneio {tournament_id} enviado para canal {channel_id}")
                except (ValueError, discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    logger.warning(f"Não foi possível enviar resultado final para canal {channel_id}: {e}")
        except Exception as e:
            logger.error(f"Erro ao enviar resultado final no canal: {e}")
        
        logger.info(f"Torneio {tournament_id} finalizado e vencedor anunciado")
    
    except Exception as e:
        logger.error(f"Erro ao anunciar vencedor do torneio: {e}")


def validate_time_control_for_mode(mode: str, tempo_inicial: int, incremento: int) -> bool:
    """Valida se o tempo especificado é válido para o modo escolhido."""
    time_control = f"{tempo_inicial}+{incremento}"

    if mode == "bullet":
        # Bullet: 1+0, 1+1, 2+1
        return time_control in ["1+0", "1+1", "2+1"]
    elif mode == "blitz":
        # Blitz: 3+0, 3+2, 5+0
        return time_control in ["3+0", "3+2", "5+0"]
    elif mode == "rapid":
        # Rapid: 10+0, 15+10, 30+0
        return time_control in ["10+0", "15+10", "30+0"]
    return False


class AcceptSwissGameView(View):
    def __init__(self, bot: commands.Bot, tournament_id: int, pairing_id: int, player1_id: str, player2_id: str, round_number: int):
        super().__init__(timeout=3600)  # 1 hora timeout
        self.bot = bot
        self.tournament_id = tournament_id
        self.pairing_id = pairing_id
        self.player1_id = player1_id
        self.player2_id = player2_id
        self.round_number = round_number
        self.finish_button = None

        # Botão Aceitar Partida
        accept_button = Button(label="Aceitar Partida", style=discord.ButtonStyle.green, custom_id=f"accept_swiss_game:{pairing_id}")

        async def _accept_callback(interaction: discord.Interaction):
            if not self.player1_id or not self.player2_id:
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("❌ Este pairing tem um jogador inválido (bye)!", ephemeral=True)
                return
            
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)

            # Verificar se o usuário é um dos jogadores do pairing
            if user_id not in [self.player1_id, self.player2_id]:
                await interaction.followup.send("❌ Você não faz parte desta partida!", ephemeral=True)
                return

            try:
                # Buscar pairing atual para verificar se já existe game_url
                pairing = await database.get_swiss_pairing_by_id(self.pairing_id)
                if not pairing:
                    await interaction.followup.send("❌ Pairing não encontrado!", ephemeral=True)
                    return

                # Se já tem URL de jogo, reusar a mesma
                if pairing.get('game_url'):
                    game_url = pairing['game_url']
                    logger.info(f"🎮 Reusando URL existente para pairing {self.pairing_id}: {game_url}")
                else:
                    # Buscar informações do torneio
                    tournament = await database.get_swiss_tournament(self.tournament_id)
                    if not tournament:
                        await interaction.followup.send("❌ Torneio não encontrado!", ephemeral=True)
                        return

                    # Determinar modo baseado no time_control
                    time_control_str = tournament.get('time_control', '10+0')
                    try:
                        total_time = int(time_control_str.split('+')[0])
                        if total_time <= 2:
                            mode = "bullet"
                        elif total_time <= 5:
                            mode = "blitz"
                        else:
                            mode = "rapid"
                    except:
                        mode = "rapid"

                    # Criar desafio aberto via Lichess API (sempre não-rated para torneios suíços)
                    import lichess_api
                    game_url = await lichess_api.create_swiss_game(time_control_str, rated=False)

                    if not game_url:
                        await interaction.followup.send("❌ Erro ao criar a partida. Tente novamente.", ephemeral=True)
                        return

                    # Atualizar o pairing com a URL do jogo
                    logger.info(f"🎮 Jogo criado para pairing {self.pairing_id}: {game_url}")
                    await database.update_swiss_pairing_game_url(self.pairing_id, game_url)

                # Buscar nomes dos jogadores para o embed
                player1_user = await self.bot.fetch_user(int(self.player1_id))
                player2_user = await self.bot.fetch_user(int(self.player2_id))

                player1_name = player1_user.display_name if player1_user else "Jogador 1"
                player2_name = player2_user.display_name if player2_user else "Jogador 2"

                # Buscar time_control do pairing/torneio
                time_control_str = pairing.get('time_control', '10+0')

                # Criar embed de desafio criado
                embed = discord.Embed(
                    title="🎯 Desafio Criado!",
                    description="Um desafio do torneio foi criado! Ambos os jogadores devem acessar o link para jogar.",
                    color=discord.Color.green()
                )
                embed.add_field(
                    name="🎲 Jogadores",
                    value=f"{player1_name} vs {player2_name}",
                    inline=False
                )
                embed.add_field(
                    name="⏱️ Tempo",
                    value=time_control_str,
                    inline=True
                )
                embed.add_field(
                    name="🎮 Acessar Desafio",
                    value=f"[Clique aqui para aceitar e jogar]({game_url})",
                    inline=False
                )
                embed.set_footer(text="Ambos os jogadores devem clicar no link para aceitar o desafio e iniciar a partida.")

                await interaction.followup.send(embed=embed, ephemeral=True)

            except Exception as e:
                logger.error(f"Erro ao aceitar partida suíça: {e}")
                await interaction.followup.send(f"❌ Erro interno: {e}", ephemeral=True)

        accept_button.callback = _accept_callback
        self.add_item(accept_button)

        self.finish_button = Button(label="Finalizar Partida", style=discord.ButtonStyle.red, custom_id=f"finish_swiss_game:{self.pairing_id}")

        async def _finish_callback(interaction: discord.Interaction):
            if not self.player1_id or not self.player2_id:
                try:
                    await interaction.response.defer(ephemeral=True)
                    await interaction.followup.send("❌ Este pairing tem um jogador inválido (bye)!", ephemeral=True)
                except:
                    pass
                return
            
            user_id = str(interaction.user.id)
            
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.errors.NotFound:
                logger.warning(f"Interação expirada para pairing {self.pairing_id}")
                return

            if user_id not in [self.player1_id, self.player2_id]:
                try:
                    await interaction.followup.send("❌ Você não faz parte desta partida!", ephemeral=True)
                except:
                    pass
                return

            try:
                pairing = await database.get_swiss_pairing_by_id(self.pairing_id)
                if not pairing:
                    try:
                        await interaction.followup.send("❌ Pairing não encontrado!", ephemeral=True)
                    except:
                        pass
                    return

                if pairing.get('status') == 'finished' or pairing.get('winner_id'):
                    try:
                        await interaction.followup.send("⚠️ Esta partida já foi finalizada!", ephemeral=True)
                    except:
                        pass
                    return

                game_url = pairing.get('game_url')
                if not game_url:
                    try:
                        await interaction.followup.send("❌ URL do jogo não encontrada!", ephemeral=True)
                    except:
                        pass
                    return

                import lichess_api
                outcome = await lichess_api.get_game_outcome(game_url)

                if not outcome:
                    try:
                        await interaction.followup.send("❌ Não foi possível obter o resultado da partida.", ephemeral=True)
                    except:
                        pass
                    return

                if not outcome.get('finished'):
                    try:
                        await interaction.followup.send("⏳ A partida ainda não terminou. Tente novamente mais tarde.", ephemeral=True)
                    except:
                        pass
                    return

                white_user = outcome['players']['white']['username']
                black_user = outcome['players']['black']['username']
                is_draw = outcome.get('is_draw', False)
                winner_color = outcome.get('winner_color')
                winner_username = outcome.get('winner_username')
                reason = outcome.get('reason', 'unknown')

                def _get_players():
                    conn = database.get_conn()
                    cur = conn.cursor()
                    p_white = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (white_user,)).fetchone() if white_user else None
                    p_black = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (black_user,)).fetchone() if black_user else None
                    conn.close()
                    return p_white, p_black

                p_white, p_black = await asyncio.to_thread(_get_players)
                p_white = dict(p_white) if p_white else None
                p_black = dict(p_black) if p_black else None

                challenger_id = pairing.get('player1_id')
                challenged_id = pairing.get('player2_id')

                winner_id = None
                loser_id = None
                result = None

                player1_id = challenger_id
                player2_id = challenged_id

                if is_draw:
                    result = 'draw'
                    winner_id = None
                    loser_id = None
                    reason_text = "Empate"
                else:
                    if winner_username:
                        if p_white and p_white.get('lichess_username') == winner_username:
                            winner_id = p_white['discord_id']
                            loser_id = p_black['discord_id'] if p_black else (player2_id if winner_id == player1_id else player1_id)
                        elif p_black and p_black.get('lichess_username') == winner_username:
                            winner_id = p_black['discord_id']
                            loser_id = p_white['discord_id'] if p_white else (player1_id if winner_id == player2_id else player2_id)

                    if not winner_id and winner_color:
                        if winner_color == 'white' and p_white:
                            winner_id = p_white['discord_id']
                            loser_id = p_black['discord_id'] if p_black else (player2_id if winner_id == player1_id else player1_id)
                        elif winner_color == 'black' and p_black:
                            winner_id = p_black['discord_id']
                            loser_id = p_white['discord_id'] if p_white else (player1_id if winner_id == player2_id else player2_id)

                    if not winner_id:
                        winner_id = player1_id
                        loser_id = player2_id

                    result = 'win'
                    reason_text = f"Vitória por {reason}"

                await database.update_swiss_pairing_result(self.pairing_id, winner_id, loser_id, result)

                try:
                    if is_draw:
                        await database.update_swiss_standings(self.tournament_id, player1_id, player2_id, result, reason)
                    else:
                        await database.update_swiss_standings(self.tournament_id, winner_id, loser_id, result, reason)
                except Exception as e:
                    logger.warning(f"Erro ao atualizar standings: {e}")

                try:
                    player1_user = await self.bot.fetch_user(int(self.player1_id))
                    player2_user = await self.bot.fetch_user(int(self.player2_id))
                    player1_name = player1_user.display_name if player1_user else "Jogador 1"
                    player2_name = player2_user.display_name if player2_user else "Jogador 2"
                except:
                    player1_name = "Jogador 1"
                    player2_name = "Jogador 2"

                tournament_info = await database.get_swiss_tournament(self.tournament_id)
                tournament_title = tournament_info.get('name', 'Torneio') if tournament_info else 'Torneio'

                if is_draw:
                    embed = discord.Embed(
                        title=tournament_title,
                        description=f"{player1_name} vs {player2_name}",
                        color=discord.Color.gold()
                    )
                else:
                    winner_name = player1_name if str(winner_id) == self.player1_id else player2_name
                    loser_name = player2_name if winner_name == player1_name else player1_name
                    embed = discord.Embed(
                        title=tournament_title,
                        description=f"{winner_name} venceu {loser_name}",
                        color=discord.Color.green()
                    )
                    embed.add_field(
                        name="🎯 Motivo",
                        value=reason_text,
                        inline=False
                    )

                embed.add_field(
                    name="🎮 Jogadores",
                    value=f"Brancas: {white_user or 'Desconhecido'}\nPretas: {black_user or 'Desconhecido'}",
                    inline=False
                )

                standings = await database.get_swiss_standings(self.tournament_id)
                standings_lines = []
                for i, player in enumerate(standings[:5], 1):
                    try:
                        user = await self.bot.fetch_user(int(player['player_id']))
                        display_name = user.display_name if user else player.get('discord_username', 'Desconhecido')
                    except:
                        display_name = player.get('discord_username', 'Desconhecido')

                    points = player.get('points', 0)
                    wins = player.get('wins', 0)
                    draws = player.get('draws', 0)
                    losses = player.get('losses', 0)

                    line = f"{i}. {display_name} - {points}pts ({wins}V/{draws}E/{losses}D)"
                    standings_lines.append(line)

                embed.add_field(
                    name="📊 Classificação Atualizada",
                    value="\n".join(standings_lines) or "Sem dados",
                    inline=False
                )

                try:
                    if tournament_info and tournament_info.get('rated', False):
                        time_control_str = tournament_info.get('time_control', '10+0')
                        total_time = int(time_control_str.split('+')[0])
                        if total_time <= 2:
                            mode = "bullet"
                        elif total_time <= 5:
                            mode = "blitz"
                        else:
                            mode = "rapid"

                        if is_draw:
                            rating_changes = await database.apply_draw_ratings(player1_id, player2_id, mode)
                        else:
                            rating_changes = await database.apply_match_ratings(winner_id, loser_id, mode)

                        if rating_changes:
                            logger.info(f"Ratings atualizados para partida suíça {self.pairing_id}")
                        # Atualiza estatísticas do perfil (wins/losses/draws) tal como ocorre no /desafiar
                        try:
                            if is_draw:
                                await database.update_player_stats(player1_id, mode, 'draw')
                                await database.update_player_stats(player2_id, mode, 'draw')
                            else:
                                # winner_id e loser_id já foram determinados acima
                                if winner_id:
                                    await database.update_player_stats(winner_id, mode, 'win')
                                if loser_id:
                                    await database.update_player_stats(loser_id, mode, 'loss')
                        except Exception as e:
                            logger.warning(f"Erro ao atualizar estatísticas do perfil após partida suíça: {e}")
                except Exception as e:
                    logger.warning(f"Erro ao atualizar ratings para partida suíça: {e}")

                # Salvar resultado no histórico de partidas
                try:
                    if tournament_info and tournament_info.get('rated', False):
                        time_control_str = tournament_info.get('time_control', '10+0')
                        total_time = int(time_control_str.split('+')[0])
                        if total_time <= 2:
                            mode = "bullet"
                        elif total_time <= 5:
                            mode = "blitz"
                        else:
                            mode = "rapid"

                        # Buscar nomes dos jogadores
                        player1_stats = await database.get_all_player_stats(player1_id)
                        player2_stats = await database.get_all_player_stats(player2_id)
                        
                        p1_name = player1_stats.get('discord_username') if player1_stats else f"Player_{player1_id}"
                        p2_name = player2_stats.get('discord_username') if player2_stats else f"Player_{player2_id}"

                        # Preparar dados de rating antes e depois
                        p1_rating_before = None
                        p2_rating_before = None
                        p1_rating_after = None
                        p2_rating_after = None

                        if 'rating_changes' in locals() and rating_changes:
                            if result == 'draw':
                                p1_data = rating_changes.get('player1', {})
                                p2_data = rating_changes.get('player2', {})
                                p1_rating_before = p1_data.get('old')
                                p1_rating_after = p1_data.get('new')
                                p2_rating_before = p2_data.get('old')
                                p2_rating_after = p2_data.get('new')
                            elif result == 'win':
                                winner_data = rating_changes.get('winner', {})
                                loser_data = rating_changes.get('loser', {})
                                if winner_id == player1_id:
                                    p1_rating_before = winner_data.get('old_rating')
                                    p1_rating_after = winner_data.get('new_rating')
                                    p2_rating_before = loser_data.get('old_rating')
                                    p2_rating_after = loser_data.get('new_rating')
                                else:
                                    p1_rating_before = loser_data.get('old_rating')
                                    p1_rating_after = loser_data.get('new_rating')
                                    p2_rating_before = winner_data.get('old_rating')
                                    p2_rating_after = winner_data.get('new_rating')

                        # Salvar no histórico
                        await database.save_game_history(
                            player1_id=player1_id,
                            player2_id=player2_id,
                            player1_name=p1_name,
                            player2_name=p2_name,
                            winner_id=winner_id if result == 'win' else None,
                            result=result,
                            mode=mode,
                            time_control=time_control_str,
                            game_url=game_url,
                            p1_rating_before=p1_rating_before,
                            p2_rating_before=p2_rating_before,
                            p1_rating_after=p1_rating_after,
                            p2_rating_after=p2_rating_after,
                        )
                        logger.info(f"✅ Partida suíça {self.pairing_id} salva no histórico")
                except Exception as e:
                    logger.error(f"❌ Erro ao salvar partida suíça no histórico: {e}", exc_info=True)

                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except:
                    pass

                try:
                    other_player_id = self.player2_id if user_id == self.player1_id else self.player1_id
                    other_user = await self.bot.fetch_user(int(other_player_id))
                    if other_user:
                        await other_user.send(embed=embed)
                        logger.info(f"Resultado da partida enviado para o outro jogador {other_player_id}")
                except Exception as e:
                    logger.warning(f"Não foi possível enviar resultado para o outro jogador: {e}")

                if interaction.message:
                    try:
                        self.finish_button.disabled = True
                        self.finish_button.style = discord.ButtonStyle.danger
                        await interaction.message.edit(view=self)
                    except Exception:
                        pass

                try:
                    all_finished = await database.check_swiss_round_completion(self.tournament_id, self.round_number)
                    if all_finished:
                        asyncio.create_task(handle_swiss_round_completion(self.bot, self.tournament_id, self.round_number))
                except Exception as e:
                    logger.warning(f"Erro ao verificar conclusão de rodada: {e}")

            except Exception as e:
                logger.error(f"Erro ao finalizar partida suíça: {e}")
                await interaction.followup.send(f"❌ Erro ao processar resultado: {e}", ephemeral=True)

        self.finish_button.callback = _finish_callback
        self.add_item(self.finish_button)


class JoinSwissView(View):
    def __init__(self, bot: commands.Bot, tournament_id: int, tournament_status: str = 'open'):
        super().__init__(timeout=None)
        self.bot = bot
        self.tournament_id = tournament_id

        # Botão Entrar
        join_button = Button(label="Entrar no Swiss", style=discord.ButtonStyle.green, custom_id=f"entrar_swiss:{tournament_id}")

        async def _join_callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            try:
                success, message = await database.join_swiss_tournament(self.tournament_id, user_id)
                if success:
                    # Atualizar embed da mensagem com novo contador de inscritos e lista
                    try:
                        tournament = await database.get_swiss_tournament(self.tournament_id)
                        participants = await database.get_swiss_tournament_participants(self.tournament_id)
                        count = len(participants) if participants is not None else 0

                        # Busca informações dos participantes
                        # Tenta usar o modo do torneio, se não conseguir calcula baseado no tempo
                        mode = get_mode_from_time_control(tournament.get('time_control', '5+0'))
                        participants_list = await format_participants_list(self.bot, participants, mode)
                        participants_text = "\n".join(participants_list)

                        # Reconstrói o embed com contador e lista atualizados
                        new_embed = discord.Embed(
                            title=f"🏆 Torneio Suíço: {tournament['name']}",
                            description=tournament.get('description', 'Torneio suíço local - Participe e teste suas habilidades!'),
                            color=discord.Color.blue()
                        )
                        # Determina o modo baseado no time control
                        modo_atual = get_mode_from_time_control(tournament.get('time_control', '5+0'))

                        info_text = f"ID do Torneio: {self.tournament_id}\nRodadas: {tournament.get('nb_rounds', 'N/A')}\nTime Control: {tournament.get('time_control', 'N/A')}\nModo: {modo_atual.title()}\nParticipantes: {count} inscritos"
                        new_embed.add_field(name="📋 Informações do Torneio", value=info_text, inline=False)

                        if participants_list:
                            new_embed.add_field(name="📝 Lista de Participantes", value=participants_text, inline=False)

                        # Busca o criador para o footer
                        try:
                            creator = await self.bot.fetch_user(int(tournament.get('created_by')))
                            new_embed.set_footer(text=f"🏅 Criado por: {creator.display_name} • Status: Aberto para inscrições", icon_url=creator.avatar.url if creator.avatar else None)
                        except:
                            new_embed.set_footer(text=f"Criado por: {tournament.get('created_by')} • Status: Aberto para inscrições")

                        # Edita a mensagem original onde o botão está anexado
                        try:
                            if interaction.message:
                                await interaction.message.edit(embed=new_embed, view=self)
                        except Exception as e:
                            logger.warning(f"Não foi possível editar mensagem do torneio: {e}")

                    except Exception as e:
                        logger.warning(f"Erro ao atualizar contador de inscritos: {e}")

                    await interaction.followup.send(f"✅ Inscrito com sucesso no torneio (ID {self.tournament_id}).", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
            except Exception as e:
                logger.error(f"Erro ao processar inscrição Swiss: {e}")
                await interaction.followup.send(f"❌ Erro interno ao tentar se inscrever: {e}", ephemeral=True)

        join_button.callback = _join_callback
        self.add_item(join_button)

        # Botão Sair
        leave_button = Button(label="Sair do Swiss", style=discord.ButtonStyle.red, custom_id=f"sair_swiss:{tournament_id}")

        async def _leave_callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            user_id = str(interaction.user.id)
            try:
                success, message = await database.leave_swiss_tournament(self.tournament_id, user_id)
                if success:
                    # Atualizar contador e lista
                    try:
                        tournament = await database.get_swiss_tournament(self.tournament_id)
                        participants = await database.get_swiss_tournament_participants(self.tournament_id)
                        count = len(participants) if participants is not None else 0

                        # Busca informações dos participantes
                        # Tenta usar o modo do torneio, se não conseguir calcula baseado no tempo
                        mode = get_mode_from_time_control(tournament.get('time_control', '5+0'))
                        participants_list = await format_participants_list(self.bot, participants, mode)
                        participants_text = "\n".join(participants_list)

                        # Reconstrói o embed com contador e lista atualizados
                        new_embed = discord.Embed(
                            title=f"🏆 Torneio Suíço: {tournament['name']}",
                            description=tournament.get('description', 'Torneio suíço local - Participe e teste suas habilidades!'),
                            color=discord.Color.blue()
                        )
                        # Determina o modo baseado no time control
                        modo_atual = get_mode_from_time_control(tournament.get('time_control', '5+0'))

                        info_text = f"ID do Torneio: {self.tournament_id}\nRodadas: {tournament.get('nb_rounds', 'N/A')}\nTime Control: {tournament.get('time_control', 'N/A')}\nModo: {modo_atual.title()}\nParticipantes: {count} inscritos"
                        new_embed.add_field(name="📋 Informações do Torneio", value=info_text, inline=False)

                        if participants_list:
                            new_embed.add_field(name="📝 Lista de Participantes", value=participants_text, inline=False)

                        # Busca o criador para o footer
                        try:
                            creator = await self.bot.fetch_user(int(tournament.get('created_by')))
                            new_embed.set_footer(text=f"🏅 Criado por: {creator.display_name} • Status: Aberto para inscrições", icon_url=creator.avatar.url if creator.avatar else None)
                        except:
                            new_embed.set_footer(text=f"Criado por: {tournament.get('created_by')} • Status: Aberto para inscrições")

                        try:
                            if interaction.message:
                                await interaction.message.edit(embed=new_embed, view=self)
                        except Exception as e:
                            logger.warning(f"Não foi possível editar mensagem do torneio: {e}")
                    except Exception as e:
                        logger.warning(f"Erro ao atualizar contador de inscritos: {e}")

                    await interaction.followup.send(f"✅ Você foi removido do torneio (ID {self.tournament_id}).", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
            except Exception as e:
                logger.error(f"Erro ao processar remoção Swiss: {e}")
                await interaction.followup.send(f"❌ Erro interno ao tentar se remover: {e}", ephemeral=True)

        leave_button.callback = _leave_callback
        self.add_item(leave_button)

        # Se o torneio não estiver aberto, desabilita ambos os botões
        if tournament_status != 'open':
            for item in self.children:
                try:
                    item.disabled = True
                except Exception:
                    pass

        # Também desabilita se estiver em andamento
        if tournament_status == 'in_progress':
            for item in self.children:
                try:
                    item.disabled = True
                except Exception:
                    pass


class Tournaments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def check_and_advance_round(self, tournament_id: int, channel: discord.TextChannel):
        """Verifica se a rodada atual foi completada e avança automaticamente."""
        try:
            # Verifica se o torneio ainda está ativo
            tournament = await database.get_tournament(tournament_id)
            if not tournament or tournament['status'] != 'in_progress':
                return

            # Busca a rodada atual
            matches = await database.get_tournament_matches(tournament_id)
            if not matches:
                return

            current_round = max([m['round_number'] for m in matches])
            # Verifica se a rodada atual foi completada
            round_complete = await database.check_round_completion(tournament_id, current_round)
            if round_complete:
                success, message = await database.advance_tournament_round(tournament_id)
                if success:
                    await self.update_tournament_standings(tournament_id)
                    is_swiss = tournament.get('mode', '').lower() == 'swiss'

                    if "Torneio finalizado" in message:
                        # Torneio acabou, anuncia vencedor
                        if tournament['winner_id']:
                            winner = await self.bot.fetch_user(int(tournament['winner_id']))
                            embed = discord.Embed(
                                title="🏆 TORNEIO FINALIZADO!",
                                description=f"Parabéns {winner.mention}! Você venceu o torneio **{tournament['name']}**!",
                                color=discord.Color.gold()
                            )
                            if is_swiss:
                                # For Swiss, announce winner via DM to participants
                                participants = await database.get_swiss_tournament_participants(tournament_id)
                                if participants:
                                    for p in participants:
                                        try:
                                            user = await self.bot.fetch_user(int(p['player_id']))
                                            if user:
                                                await user.send(embed=embed)
                                        except Exception as e:
                                            logger.warning(f"Não foi possível enviar DM para participante {p['discord_username']}: {e}")
                            else:
                                # For other tournaments, announce publicly
                                await channel.send(embed=embed)
                        logger.info(f"Torneio {tournament_id} finalizado automaticamente")
                    else:
                        # Nova rodada foi criada, notifica jogadores se for torneio suíço
                        if is_swiss:
                            try:
                                next_round = current_round + 1
                                await database.generate_and_save_swiss_round(tournament_id, next_round)
                                await notify_swiss_pairings(self.bot, tournament_id, next_round)
                                logger.info(f"Torneio {tournament_id}: Nova rodada {next_round} gerada e jogadores notificados")
                            except Exception as e:
                                logger.error(f"Erro ao gerar nova rodada {next_round} para torneio suíço {tournament_id}: {e}")
                        # Continua verificando para a próxima rodada
                        logger.info(f"Torneio {tournament_id}: Rodada {current_round} completada, avançando automaticamente")
                else:
                    logger.warning(f"Falha ao avançar rodada automaticamente para torneio {tournament_id}: {message}")
        except Exception as e:
            logger.error(f"Erro ao verificar/avançar rodada para torneio {tournament_id}: {e}")

    async def update_tournament_standings(self, tournament_id: int):
        # Placeholder method - implement standings update logic here
        pass

    @app_commands.command(name="criar_swiss", description="Cria um torneio suíço local.")
    @app_commands.describe(
        nome="Nome do torneio (obrigatório)",
        numero_rodadas="Número de rodadas (obrigatório)",
        modo="Modo do torneio: bullet, blitz ou rapid (obrigatório)",
        tempo_inicial="Tempo inicial em minutos (obrigatório)",
        incremento="Incremento em segundos (obrigatório)",
        descricao="Descrição do torneio (obrigatório)",
        rated="Se o torneio vale rating interno (obrigatório)"
    )
    async def criar_swiss(self, interaction: discord.Interaction, nome: str, numero_rodadas: int, modo: Literal["bullet", "blitz", "rapid"], tempo_inicial: int, incremento: int, descricao: str, rated: bool, min_rating: int = None, max_rating: int = None):
        """Comando para criar um torneio suíço local e salvar no banco de dados."""
        await interaction.response.defer()

        # Valida se o tempo está correto para o modo escolhido
        if not validate_time_control_for_mode(modo, tempo_inicial, incremento):
            valid_times = {
                "bullet": ["1+0", "1+1", "2+1"],
                "blitz": ["3+0", "3+2", "5+0"],
                "rapid": ["10+0", "15+10", "30+0"]
            }
            await interaction.followup.send(
                f"❌ Tempo inválido para o modo **{modo}**!\n\n"
                f"**Tempos válidos para {modo}:**\n" +
                "\n".join(f"• {time}" for time in valid_times[modo]),
                ephemeral=True
            )
            return

        # Monta o time control como string "minutos+incremento"
        time_control = f"{int(tempo_inicial)}+{int(incremento)}"

        try:
            created_by = str(interaction.user.id)
            channel_id = str(interaction.channel.id) if interaction.channel else None
            tournament_id = await database.create_swiss_tournament(nome, descricao, time_control, numero_rodadas, created_by, rated, min_rating, max_rating, channel_id)

            # Busca participantes (deve estar vazio na criação)
            participants = await database.get_swiss_tournament_participants(tournament_id)
            participants_list = await format_participants_list(self.bot, participants, modo)
            participants_text = "\n".join(participants_list)

            # Envia embed público com botões para inscrição
            public_embed = discord.Embed(
                title=f"🏆 Torneio Suíço: {nome}",
                description=descricao or "Torneio suíço local - Participe e teste suas habilidades!",
                color=discord.Color.blue()
            )
            info_text = f"ID do Torneio: {tournament_id}\nRodadas: {numero_rodadas}\nTime Control: {time_control}\nModo: {modo.title()}\nParticipantes: {len(participants) if participants else 0} inscritos"
            public_embed.add_field(name="📋 Informações do Torneio", value=info_text, inline=False)

            if participants_list:
                public_embed.add_field(name="📝 Lista de Participantes", value=participants_text, inline=False)

            public_embed.set_footer(text=f"🏅 Criado por: {interaction.user.display_name} • Status: Aberto para inscrições", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

            view = JoinSwissView(self.bot, tournament_id, 'open')
            await interaction.followup.send(embed=public_embed, view=view)

        except Exception as e:
            logger.error(f"Erro ao criar torneio suíço: {e}")
            await interaction.followup.send(f"❌ Erro ao criar torneio suíço: {e}", ephemeral=True)

    @app_commands.command(name="entrar_swiss", description="Envia uma mensagem com botão para entrar em um torneio suíço (use com ID do torneio).")
    @app_commands.describe(tournament_id="ID do torneio suíço")
    async def entrar_swiss(self, interaction: discord.Interaction, tournament_id: int):
        """Envia um embed com um botão para participantes se inscreverem no torneio suíço."""
        await interaction.response.defer()

        tournament = await database.get_swiss_tournament(tournament_id)
        if not tournament:
            await interaction.followup.send(f"❌ Torneio suíço com ID {tournament_id} não encontrado.", ephemeral=True)
            return
        participants = await database.get_swiss_tournament_participants(tournament_id)
        count = len(participants) if participants is not None else 0

        # Busca informações dos participantes
        # Tenta usar o modo do torneio, se não conseguir calcula baseado no tempo
        mode = get_mode_from_time_control(tournament.get('time_control', '5+0'))
        participants_list = await format_participants_list(self.bot, participants, mode)
        participants_text = "\n".join(participants_list)

        embed = discord.Embed(
            title=f"🏆 Torneio Suíço: {tournament['name']}",
            description=tournament.get('description', 'Torneio suíço local - Participe e teste suas habilidades!'),
            color=discord.Color.blue()
        )
        # Determina o modo baseado no time control
        modo_atual = get_mode_from_time_control(tournament.get('time_control', '5+0'))

        info_text = f"ID do Torneio: {tournament_id}\nRodadas: {tournament.get('nb_rounds', 'N/A')}\nTime Control: {tournament.get('time_control', 'N/A')}\nModo: {modo_atual.title()}\nParticipantes: {count} inscritos"
        embed.add_field(name="📋 Informações do Torneio", value=info_text, inline=False)

        if participants_list:
            embed.add_field(name="📝 Lista de Participantes", value=participants_text, inline=False)

        # Busca o criador para o footer
        try:
            creator = await self.bot.fetch_user(int(tournament.get('created_by')))
            embed.set_footer(text=f"🏅 Criado por: {creator.display_name} • Status: Aberto para inscrições", icon_url=creator.avatar.url if creator.avatar else None)
        except:
            embed.set_footer(text=f"Criado por: {tournament.get('created_by')} • Status: Aberto para inscrições")

        view = JoinSwissView(self.bot, tournament_id, tournament.get('status', 'open'))
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="iniciar_torneio", description="Inicia um torneio (suíço ou normal) com o ID especificado.")
    @app_commands.describe(tournament_id="ID do torneio a ser iniciado")
    async def iniciar_torneio(self, interaction: discord.Interaction, tournament_id: int):
        """Inicia um torneio, criando as primeiras partidas."""
        await interaction.response.defer()

        try:
            # Primeiro verifica se é um torneio suíço
            swiss_tournament = await database.get_swiss_tournament(tournament_id)
            if swiss_tournament:
                # É um torneio suíço
                if swiss_tournament['status'] != 'open':
                    await interaction.followup.send(f"❌ O torneio suíço #{tournament_id} não pode ser iniciado (status: {swiss_tournament['status']}).", ephemeral=True)
                    return

                success, message = await database.start_swiss_tournament(tournament_id)
                if success:
                    # Gera a primeira rodada do torneio suíço
                    try:
                        await database.generate_and_save_swiss_round(tournament_id, 1)
                        # Notifica jogadores sobre os pairings via DM
                        await notify_swiss_pairings(self.bot, tournament_id, 1)

                        embed = discord.Embed(
                            title="✅ Torneio Suíço Iniciado",
                            description=f"O torneio **{swiss_tournament['name']}** foi iniciado com sucesso!\n\nA primeira rodada foi gerada automaticamente e os jogadores foram notificados via DM.",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="ID do Torneio", value=str(tournament_id), inline=True)
                        embed.add_field(name="Tipo", value="Suíço", inline=True)
                        embed.add_field(name="Status", value="Em andamento", inline=True)
                        await interaction.followup.send(embed=embed)
                    except Exception as e:
                        logger.error(f"Erro ao gerar primeira rodada do torneio suíço {tournament_id}: {e}")
                        await interaction.followup.send(f"⚠️ Torneio iniciado, mas houve um erro ao gerar a primeira rodada: {e}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ Erro ao iniciar torneio suíço: {message}", ephemeral=True)
            else:
                # Verifica se é um torneio normal
                tournament = await database.get_tournament(tournament_id)
                if not tournament:
                    await interaction.followup.send(f"❌ Torneio com ID {tournament_id} não encontrado.", ephemeral=True)
                    return

                if tournament['status'] != 'open':
                    await interaction.followup.send(f"❌ O torneio #{tournament_id} não pode ser iniciado (status: {tournament['status']}).", ephemeral=True)
                    return

                success, message = await database.start_tournament(tournament_id)
                if success:
                    embed = discord.Embed(
                        title="✅ Torneio Iniciado",
                        description=f"O torneio **{tournament['name']}** foi iniciado com sucesso!\n\nAs primeiras partidas foram criadas automaticamente.",
                        color=discord.Color.green()
                    )
                    embed.add_field(name="ID do Torneio", value=str(tournament_id), inline=True)
                    embed.add_field(name="Tipo", value="Eliminação", inline=True)
                    embed.add_field(name="Status", value="Em andamento", inline=True)
                    await interaction.followup.send(embed=embed)
                else:
                    await interaction.followup.send(f"❌ Erro ao iniciar torneio: {message}", ephemeral=True)

        except Exception as e:
            logger.error(f"Erro ao iniciar torneio {tournament_id}: {e}")
            await interaction.followup.send(f"❌ Erro interno ao iniciar torneio: {e}", ephemeral=True)


# To register this cog, the main bot file should load this extension appropriately
async def setup(bot: commands.Bot):
    """Entry point for the extension loader. Registers the Tournaments cog."""
    await bot.add_cog(Tournaments(bot))
