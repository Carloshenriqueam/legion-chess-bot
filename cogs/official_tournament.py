# cogs/official_tournament.py
from discord.ext import commands
import discord
from discord import app_commands
from discord.ui import View, Button
import logging
import database
import asyncio
from typing import Literal
import io
try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger(__name__)

async def get_player_rating(discord_id: str, mode: str) -> int:
    """Busca o rating de um jogador para um modo específico."""
    try:
        player_stats = await database.get_all_player_stats(discord_id)
        if player_stats:
            rating_key = f"rating_{mode}"
            return player_stats.get(rating_key, 1200)
        return 1200
    except Exception as e:
        logger.warning(f"Erro ao buscar rating para {discord_id}: {e}")
        return 1200

def draw_match_box(draw, x, y, match, player_names, font, w, h):
    """Desenha a caixa de uma partida específica."""
    # Player 1
    p1_id = match['player1_id']
    p1_name = str(player_names.get(p1_id, "Bye" if p1_id is None else f"ID: {p1_id[:4]}"))
    if len(p1_name) > 16: p1_name = p1_name[:14] + ".."
    
    p1_bg = (47, 49, 54) # Dark gray
    p1_border = (100, 100, 100)
    if match['winner_id'] == p1_id and p1_id is not None:
        p1_bg = (46, 125, 50) # Green
        p1_border = (46, 204, 113)
        
    draw.rectangle([x, y, x + w, y + h], fill=p1_bg, outline=p1_border)
    draw.text((x + 5, y + 6), p1_name, fill="white", font=font)
    
    # Player 2
    p2_id = match['player2_id']
    p2_name = str(player_names.get(p2_id, "Bye" if p2_id is None else f"ID: {p2_id[:4]}"))
    if len(p2_name) > 16: p2_name = p2_name[:14] + ".."
    
    p2_bg = (47, 49, 54)
    p2_border = (100, 100, 100)
    if match['winner_id'] == p2_id and p2_id is not None:
        p2_bg = (46, 125, 50)
        p2_border = (46, 204, 113)
        
    draw.rectangle([x, y + h, x + w, y + 2 * h], fill=p2_bg, outline=p2_border)
    draw.text((x + 5, y + h + 6), p2_name, fill="white", font=font)

def create_bracket_image(matches, player_names):
    """Gera uma imagem PNG do bracket."""
    if not HAS_PIL:
        logger.error("Biblioteca Pillow (PIL) não encontrada. Instale com 'pip install Pillow'.")
        return None

    # Agrupa por rodada
    rounds = {}
    for m in matches:
        r = m['round_number']
        if r not in rounds:
            rounds[r] = []
        rounds[r].append(m)
    
    if not rounds:
        return None
        
    # Ordena partidas em cada rodada
    for r in rounds:
        rounds[r].sort(key=lambda x: x['match_number'])
        
    num_rounds = max(rounds.keys())
    # Assume que a rodada 1 define a altura máxima
    max_matches_in_round = len(rounds.get(1, []))
    if max_matches_in_round == 0:
        max_matches_in_round = max(len(m) for m in rounds.values())

    # Dimensões
    BOX_W = 170
    BOX_H = 25
    MATCH_H = 2 * BOX_H # Altura total do bloco da partida
    MATCH_GAP = 20 # Espaço vertical entre partidas
    ROUND_GAP = 60 # Espaço horizontal entre rodadas
    
    # Tamanho do canvas
    width = num_rounds * (BOX_W + ROUND_GAP) + BOX_W
    height = max_matches_in_round * (MATCH_H + MATCH_GAP) + MATCH_GAP + 20
    
    width = max(width, 400)
    height = max(height, 200)
    
    image = Image.new('RGB', (width, height), (54, 57, 63)) # Discord dark bg
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("arial.ttf", 14)
    except:
        font = ImageFont.load_default()
        
    # Armazena o centro Y de cada partida: (round, match_num) -> y
    centers = {}
    
    # Desenha Rodada 1
    start_x = 20
    start_y = 20
    
    for i, match in enumerate(rounds.get(1, [])):
        m_num = match['match_number']
        x = start_x
        y = start_y + i * (MATCH_H + MATCH_GAP)
        draw_match_box(draw, x, y, match, player_names, font, BOX_W, BOX_H)
        centers[(1, m_num)] = y + MATCH_H / 2
        
    # Desenha rodadas subsequentes
    for r in range(2, num_rounds + 1):
        current_matches = rounds.get(r, [])
        x = start_x + (r - 1) * (BOX_W + ROUND_GAP)
        
        for match in current_matches:
            m_num = match['match_number']
            prev_1 = 2 * m_num - 1
            prev_2 = 2 * m_num
            
            y1 = centers.get((r - 1, prev_1))
            y2 = centers.get((r - 1, prev_2))
            
            if y1 is not None and y2 is not None:
                y_center = (y1 + y2) / 2
                y = y_center - MATCH_H / 2
                
                # Linhas de conexão
                line_x_start = x - ROUND_GAP
                line_x_mid = x - ROUND_GAP / 2
                
                # Linhas saindo das partidas anteriores
                draw.line([(line_x_start, y1), (line_x_mid, y1)], fill=(200, 200, 200), width=2)
                draw.line([(line_x_start, y2), (line_x_mid, y2)], fill=(200, 200, 200), width=2)
                # Linha vertical conectando
                draw.line([(line_x_mid, y1), (line_x_mid, y2)], fill=(200, 200, 200), width=2)
                # Linha horizontal para a partida atual
                draw.line([(line_x_mid, y_center), (x, y_center)], fill=(200, 200, 200), width=2)
                
                draw_match_box(draw, x, y, match, player_names, font, BOX_W, BOX_H)
                centers[(r, m_num)] = y_center
                
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer

async def notify_bracket_players(bot, tournament_id: int, channel: discord.TextChannel):
    """Exibe desafios do bracket no chat."""
    try:
        tournament = await database.get_tournament(tournament_id)
        if not tournament:
            return

        # Busca partidas da rodada 1
        matches = await database.get_tournament_matches(tournament_id, round_num=1)
        if not matches:
            return

        time_control = tournament.get('time_control', '10+0')
        mode = tournament.get('mode', 'rapid').title()

        # Para cada partida, exibe no chat
        for match in matches:
            if match['status'] == 'finished' and match.get('player2_id') is None:
                # Bye - anuncia no chat
                try:
                    player = await bot.fetch_user(int(match['player1_id']))
                    if player:
                        embed = discord.Embed(
                            title=f"🏆 Torneio: {tournament['name']} - Rodada 1",
                            description=f"{player.mention} recebeu um **bye** nesta rodada e avança automaticamente para a próxima rodada!",
                            color=discord.Color.orange()
                        )
                        embed.add_field(name="Status", value="✅ Avançou automaticamente", inline=False)
                        await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Erro ao anunciar bye no chat: {e}")
            elif match.get('player2_id'):
                # Partida normal - exibe desafio no chat
                try:
                    player1 = await bot.fetch_user(int(match['player1_id']))
                    player2 = await bot.fetch_user(int(match['player2_id']))
                    challenge_id = match.get('challenge_id')
                    
                    if challenge_id and player1 and player2:
                        from cogs.chess import ChallengeResponseView
                        
                        embed_chat = discord.Embed(
                            title="⚔️ Desafio do Torneio!",
                            description=f"{player1.mention} vs {player2.mention} - **Rodada 1**",
                            color=0xCD0000
                        )
                        embed_chat.add_field(
                            name="Detalhes do Desafio:",
                            value=f"⏱️ Tempo: {time_control} | 🏆 Rating: {'Sim' if tournament.get('rated') else 'Não'} | 🆔 ID: #{challenge_id}",
                            inline=False
                        )
                        embed_chat.add_field(
                            name="Torneio:",
                            value=f"🏆 **{tournament['name']}**",
                            inline=False
                        )
                        embed_chat.set_footer(text=f"{player2.display_name}, use /aceitar {challenge_id} ou /recusar {challenge_id}")

                        # Timeout=None para que os botões não expirem em torneios longos
                        view = ChallengeResponseView(bot, challenge_id, timeout=None)
                        try:
                            message = await channel.send(embed=embed_chat, view=view)
                            view.message = message
                        except Exception as e:
                            logger.error(f"Erro ao exibir desafio no chat: {e}")
                        
                        # Envia notificação via DM para os jogadores
                        for player in [player1, player2]:
                            try:
                                dm_embed = discord.Embed(
                                    title="🏆 Nova Partida de Torneio!",
                                    description=f"Sua partida contra **{player2.display_name if player == player1 else player1.display_name}** está pronta.",
                                    color=discord.Color.gold()
                                )
                                dm_embed.add_field(name="Torneio", value=tournament['name'], inline=False)
                                dm_embed.add_field(name="ID do Desafio", value=f"#{challenge_id}", inline=True)
                                dm_embed.add_field(name="Tempo", value=time_control, inline=True)
                                dm_embed.set_footer(text="Clique abaixo para aceitar ou use /aceitar no servidor.")
                                
                                dm_view = ChallengeResponseView(bot, challenge_id, timeout=None)
                                await player.send(embed=dm_embed, view=dm_view)
                            except discord.Forbidden:
                                logger.warning(f"Não foi possível enviar DM de torneio para {player.display_name}")
                            except Exception as e:
                                logger.error(f"Erro ao enviar DM de torneio para {player.display_name}: {e}")

                except Exception as e:
                    logger.error(f"Erro ao exibir desafio da partida {match.get('id')} no chat: {e}")

    except Exception as e:
        logger.error(f"Erro ao exibir desafios do bracket no chat: {e}", exc_info=True)


async def display_bracket_in_channel(bot, tournament_id: int, channel: discord.TextChannel):
    """Exibe o bracket no canal gerando uma imagem."""
    try:
        tournament = await database.get_tournament(tournament_id)
        if not tournament:
            return

        matches = await database.get_tournament_matches(tournament_id)
        if not matches:
            return

        participants = await database.get_tournament_participants(tournament_id)
        player_names = {}
        
        for p in participants:
            try:
                user = await bot.fetch_user(int(p['player_id']))
                player_names[p['player_id']] = user.display_name if user else p.get('discord_username', f"Player {p['player_id'][:4]}")
            except:
                player_names[p['player_id']] = p.get('discord_username', f"Player {p['player_id'][:4]}")

        # Gera a imagem do bracket
        image_buffer = await asyncio.to_thread(create_bracket_image, matches, player_names)
        
        if image_buffer:
            file = discord.File(fp=image_buffer, filename="bracket.png")
            embed = discord.Embed(title=f"🏆 Bracket - {tournament['name']}", color=discord.Color.gold())
            embed.set_image(url="attachment://bracket.png")
            await channel.send(embed=embed, file=file)
            logger.info(f"✅ Bracket exibido como imagem para torneio {tournament_id}")
        else:
            logger.warning(f"Falha ao gerar imagem do bracket para torneio {tournament_id}")
        return

    except Exception as e:
        logger.error(f"Erro ao exibir bracket no canal: {e}", exc_info=True)
        raise


async def format_bracket_participants_list(bot, participants, mode: str, limit: int = 20) -> list:
    """Formata lista de participantes ordenada por rating (maior para menor) para torneios de bracket."""
    if not participants:
        return ["Nenhum participante ainda."]

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
            'id': p['player_id']
        })

    participant_data.sort(key=lambda x: (-x['rating'], x['id']))

    participants_list = []
    for i, data in enumerate(participant_data[:limit], 1):
        participants_list.append(f"{i}. {data['name']} ({data['rating']})")

    if len(participants) > limit:
        participants_list.append(f"... e mais {len(participants) - limit} participantes")

    return participants_list

class JoinOfficialTournamentView(View):
    def __init__(self, bot: commands.Bot, tournament_id: int, mode: str):
        super().__init__(timeout=None)
        self.bot = bot
        self.tournament_id = tournament_id
        self.mode = mode

        join_button = Button(label="Entrar no Torneio", style=discord.ButtonStyle.green, custom_id=f"join_official:{tournament_id}")
        join_button.callback = self.join_callback
        self.add_item(join_button)

        leave_button = Button(label="Sair do Torneio", style=discord.ButtonStyle.red, custom_id=f"leave_official:{tournament_id}")
        leave_button.callback = self.leave_callback
        self.add_item(leave_button)

    async def update_embed(self, interaction: discord.Interaction):
        """Atualiza o embed da mensagem com a lista de participantes atualizada."""
        try:
            tournament = await database.get_tournament(self.tournament_id)
            if not tournament:
                # O torneio pode ter sido removido; desabilita botões.
                for item in self.children:
                    item.disabled = True
                await interaction.message.edit(view=self)
                return

            participants = await database.get_tournament_participants(self.tournament_id)
            count = len(participants) if participants is not None else 0
            
            participants_list = await format_bracket_participants_list(self.bot, participants, self.mode)
            participants_text = "\n".join(participants_list)

            new_embed = interaction.message.embeds[0]
            # Limpa o campo de participantes para reescrevê-lo
            for i, field in enumerate(new_embed.fields):
                if field.name == "📝 Lista de Participantes":
                    new_embed.remove_field(i)
                    break
            
            new_embed.add_field(name="📝 Lista de Participantes", value=participants_text or "Nenhum participante ainda.", inline=False)
            
            # Atualiza o contador no campo de informações
            for i, field in enumerate(new_embed.fields):
                if field.name == "📋 Informações do Torneio":
                    lines = field.value.split('\n')
                    for j, line in enumerate(lines):
                        if line.startswith("Participantes:"):
                            lines[j] = f"Participantes: {count} inscritos"
                            break
                    new_embed.set_field_at(i, name="📋 Informações do Torneio", value="\n".join(lines), inline=False)
                    break

            await interaction.message.edit(embed=new_embed, view=self)

        except Exception as e:
            logger.error(f"Erro ao atualizar embed do torneio oficial: {e}")

    async def join_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        try:
            # Requerimento de Lichess username
            player_data = await database.get_player_by_discord_id(user_id)
            if not player_data or not player_data.get('lichess_username'):
                await interaction.followup.send(
                    "❌ **Username Lichess obrigatório!**\n"
                    "Use o comando `/registrar_lichess <username>` para participar.",
                    ephemeral=True
                )
                return

            success, message = await database.join_tournament(self.tournament_id, user_id)
            if success:
                await interaction.followup.send(f"✅ Inscrito com sucesso no torneio!", ephemeral=True)
                await self.update_embed(interaction)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao processar inscrição em torneio oficial: {e}")
            await interaction.followup.send(f"❌ Erro interno ao tentar se inscrever: {e}", ephemeral=True)

    async def leave_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user_id = str(interaction.user.id)

        try:
            success, message = await database.leave_tournament(self.tournament_id, user_id)
            if success:
                await interaction.followup.send(f"✅ Você saiu do torneio.", ephemeral=True)
                await self.update_embed(interaction)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao processar saída de torneio oficial: {e}")
            await interaction.followup.send(f"❌ Erro interno ao tentar sair: {e}", ephemeral=True)

class OfficialTournament(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    official_tournament_group = app_commands.Group(name="torneio_oficial", description="Comandos para gerenciar torneios oficiais com brackets.")

    @official_tournament_group.command(name="criar", description="Cria um novo torneio oficial de eliminação simples.")
    @app_commands.describe(
        nome="Nome do torneio",
        descricao="Uma breve descrição do torneio",
        modo="Modo de jogo (bullet, blitz, rapid)",
        tempo_inicial="Tempo inicial em minutos para cada jogador",
        incremento="Incremento em segundos por jogada"
    )
    async def criar_torneio(self, interaction: discord.Interaction, nome: str, descricao: str, modo: Literal["bullet", "blitz", "rapid"], tempo_inicial: int, incremento: int):
        await interaction.response.defer() 
        
        time_control = f"{tempo_inicial}+{incremento}"
        created_by = str(interaction.user.id)

        try:
            # Usando min_participants=2 e max_participants=64 como padrão para brackets
            tournament_id = await database.create_tournament(
                name=nome,
                description=descricao,
                mode=modo,
                time_control=time_control,
                max_participants=64,
                min_participants=2,
                created_by=created_by,
                is_automatic=False, # Torneios oficiais são manuais
                rated=True # Torneios oficiais valem rating
            )

            public_embed = discord.Embed(
                title=f"🏆 Torneio Oficial: {nome}",
                description=descricao,
                color=discord.Color.dark_gold()
            )
            info_text = (
                f"**ID do Torneio:** {tournament_id}\n"
                f"**Modo:** {modo.title()}\n"
                f"**Time Control:** {time_control}\n"
                f"**Formato:** Eliminação Simples (Bracket)\n"
                f"**Participantes:** 0 inscritos"
            )
            public_embed.add_field(name="📋 Informações do Torneio", value=info_text, inline=False)
            public_embed.add_field(name="📝 Lista de Participantes", value="Nenhum participante ainda.", inline=False)
            public_embed.set_footer(text=f"Legion Chess")

            view = JoinOfficialTournamentView(self.bot, tournament_id, modo)
            await interaction.followup.send(embed=public_embed, view=view)

        except Exception as e:
            logger.error(f"Erro ao criar torneio oficial: {e}")
            await interaction.followup.send(f"❌ Erro ao criar torneio: {e}", ephemeral=True)


    @official_tournament_group.command(name="iniciar", description="Inicia um torneio oficial, gerando os brackets da primeira rodada.")
    @app_commands.describe(tournament_id="O ID do torneio a ser iniciado.")
    async def iniciar_torneio(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer(ephemeral=True)

        try:
            tournament = await database.get_tournament(tournament_id)
            if not tournament:
                await interaction.followup.send(f"❌ Torneio com ID {tournament_id} não encontrado.", ephemeral=True)
                return

            # Permissão: Apenas o criador ou admin pode iniciar
            if str(interaction.user.id) != tournament['created_by'] and not interaction.user.guild_permissions.administrator:
                await interaction.followup.send("❌ Apenas o criador do torneio ou um administrador pode iniciá-lo.", ephemeral=True)
                return

            if tournament['status'] != 'open':
                await interaction.followup.send(f"❌ O torneio não pode ser iniciado (Status: {tournament['status']}).", ephemeral=True)
                return

            participants = await database.get_tournament_participants(tournament_id)
            if len(participants) < 2:
                await interaction.followup.send("❌ São necessários pelo menos 2 participantes para iniciar.", ephemeral=True)
                return

            # Obtém o channel_id do canal onde o torneio está sendo iniciado
            channel_id = str(interaction.channel.id) if interaction.channel else None
            success, message = await database.start_bracket_tournament(tournament_id, channel_id)

            if success:
                # Desativa os botões de entrar/sair na mensagem original
                try:
                    # Tenta buscar a mensagem original do torneio
                    # Procura pela mensagem mais recente com embed do torneio
                    async for message in interaction.channel.history(limit=50):
                        if message.embeds and len(message.embeds) > 0:
                            embed = message.embeds[0]
                            if embed.title and f"Torneio Oficial" in embed.title:
                                # Verifica se é o torneio correto pelo ID no embed
                                for field in embed.fields:
                                    if field.name == "📋 Informações do Torneio" and str(tournament_id) in field.value:
                                        view = discord.ui.View.from_message(message)
                                        if view:
                                            for item in view.children:
                                                item.disabled = True
                                            await message.edit(view=view)
                                        break
                                break
                except (discord.NotFound, discord.HTTPException, AttributeError) as e:
                    # Ignora erros silenciosamente - não é crítico se não conseguir desabilitar os botões
                    logger.debug(f"Não foi possível desabilitar os botões do torneio {tournament_id}: {e}")
                except Exception as e:
                    logger.warning(f"Erro ao desabilitar botões do torneio {tournament_id}: {e}")

                await interaction.followup.send(f"✅ O torneio **{tournament['name']}** foi iniciado! Os brackets foram gerados.", ephemeral=True)

                # Notifica jogadores sobre suas partidas e exibe o bracket
                await notify_bracket_players(self.bot, tournament_id, interaction.channel)
                await display_bracket_in_channel(self.bot, tournament_id, interaction.channel)

            else:
                await interaction.followup.send(f"❌ Erro ao iniciar o torneio: {message}", ephemeral=True)

        except Exception as e:
            logger.error(f"Erro ao iniciar torneio oficial: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Erro interno ao iniciar o torneio: {e}", ephemeral=True)


    @official_tournament_group.command(name="bracket", description="Exibe o bracket atual de um torneio oficial.")
    @app_commands.describe(tournament_id="O ID do torneio.")
    async def ver_bracket(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer()
        try:
            tournament = await database.get_tournament(tournament_id)
            if not tournament:
                await interaction.followup.send(f"❌ Torneio com ID {tournament_id} não encontrado.", ephemeral=True)
                return

            matches = await database.get_tournament_matches(tournament_id)
            if not matches:
                await interaction.followup.send("Nenhuma partida encontrada para este torneio ainda.", ephemeral=True)
                return

            participants = await database.get_tournament_participants(tournament_id)
            player_names = {}
            
            # Busca nomes dos jogadores
            for p in participants:
                try:
                    user = await self.bot.fetch_user(int(p['player_id']))
                    player_names[p['player_id']] = user.display_name if user else p.get('discord_username', f"Player {p['player_id'][:4]}")
                except:
                    player_names[p['player_id']] = p.get('discord_username', f"Player {p['player_id'][:4]}")
            
            # Gera a imagem do bracket
            image_buffer = await asyncio.to_thread(create_bracket_image, matches, player_names)
            
            if image_buffer:
                file = discord.File(fp=image_buffer, filename="bracket.png")
                embed = discord.Embed(title=f"🏆 Bracket - {tournament['name']}", color=discord.Color.gold())
                embed.set_image(url="attachment://bracket.png")
                await interaction.followup.send(embed=embed, file=file)
            else:
                await interaction.followup.send("Não foi possível gerar a imagem do bracket.", ephemeral=True)

        except Exception as e:
            logger.error(f"Erro ao exibir bracket: {e}", exc_info=True)
            await interaction.followup.send(f"❌ Erro interno ao exibir o bracket: {e}", ephemeral=True)

    @official_tournament_group.command(name="forcar_vencedor", description="[Admin] Define manualmente o vencedor de uma partida em caso de disputa.")
    @app_commands.describe(tournament_id="ID do torneio", round_number="Número da rodada", match_number="Número da partida", vencedor="Usuário vencedor")
    @app_commands.checks.has_permissions(administrator=True)
    async def forcar_vencedor(self, interaction: discord.Interaction, tournament_id: int, round_number: int, match_number: int, vencedor: discord.User):
        await interaction.response.defer(ephemeral=True)
        try:
            success, message = await database.force_tournament_match_winner(tournament_id, round_number, match_number, str(vencedor.id))
            
            if success:
                await interaction.followup.send(f"✅ Vencedor da partida {match_number} (Rodada {round_number}) definido como {vencedor.mention}.", ephemeral=True)
                # Tenta avançar o torneio caso essa fosse a última partida
                await self.bot.get_cog('Tournaments').check_and_advance_round(tournament_id, interaction.channel)
            else:
                await interaction.followup.send(f"❌ Erro: {message}", ephemeral=True)
        except Exception as e:
            logger.error(f"Erro ao forçar vencedor: {e}")
            await interaction.followup.send(f"❌ Erro interno: {e}", ephemeral=True)

    @official_tournament_group.command(name="dados_json", description="[Dev] Obtém o JSON do bracket para integração com site.")
    @app_commands.checks.has_permissions(administrator=True)
    async def dados_json(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer(ephemeral=True)
        data = await database.get_tournament_bracket_data(tournament_id)
        if data:
            import json
            # Envia como arquivo pois pode ser grande
            file = discord.File(io.StringIO(json.dumps(data, indent=2)), filename=f"tournament_{tournament_id}.json")
            await interaction.followup.send("📂 Dados do torneio para integração:", file=file, ephemeral=True)
        else:
            await interaction.followup.send("❌ Torneio não encontrado.", ephemeral=True)

    @official_tournament_group.command(name="partidas_pendentes", description="Lista as partidas que ainda não foram jogadas no torneio.")
    @app_commands.describe(tournament_id="ID do torneio")
    async def partidas_pendentes(self, interaction: discord.Interaction, tournament_id: int):
        await interaction.response.defer()
        try:
            matches = await database.get_tournament_matches(tournament_id)
            if not matches:
                await interaction.followup.send("Nenhuma partida encontrada.", ephemeral=True)
                return

            # Filtra apenas partidas pendentes (status 'pending')
            pending_matches = [m for m in matches if m['status'] == 'pending']
            
            if not pending_matches:
                await interaction.followup.send("✅ Todas as partidas geradas já foram concluídas!", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"⏳ Partidas Pendentes - Torneio #{tournament_id}",
                color=discord.Color.orange()
            )

            for match in pending_matches:
                p1_name = match.get('player1_name', 'Desconhecido')
                p2_name = match.get('player2_name', 'Desconhecido')
                challenge_id = match.get('challenge_id', 'N/A')
                
                embed.add_field(
                    name=f"Match {match['match_number']} (Rodada {match['round_number']})",
                    value=f"👤 **{p1_name}** vs **{p2_name}**\n🆔 Desafio: `{challenge_id}`",
                    inline=False
                )
            
            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Erro ao listar partidas pendentes: {e}")
            await interaction.followup.send("❌ Erro ao buscar partidas pendentes.", ephemeral=True)

    async def generate_bracket_string(self, matches: list, player_names: dict) -> str:
        """Gera uma representação em string do bracket do torneio."""
        if not matches:
            return "O bracket ainda não foi gerado."

        matches_by_round = {}
        for match in matches:
            round_num = match['round_number']
            if round_num not in matches_by_round:
                matches_by_round[round_num] = []
            matches_by_round[round_num].append(match)

        # Ordenar partidas dentro das rodadas
        for round_num in matches_by_round:
            matches_by_round[round_num].sort(key=lambda m: m['match_number'])

        output_lines = []
        max_rounds = max(matches_by_round.keys())

        # Esta é uma implementação simplificada. Um bracket gráfico real em texto é muito complexo.
        # Vamos listar as partidas por rodada.
        
        for i in range(1, max_rounds + 2): # Itera até uma rodada a mais para a final
            if i not in matches_by_round and i > 1 and i-1 in matches_by_round:
                 # Checa se o torneio acabou
                last_round_matches = matches_by_round[i-1]
                if len(last_round_matches) == 1 and last_round_matches[0]['winner_id']:
                    winner_name = player_names.get(last_round_matches[0]['winner_id'], "Vencedor Desconhecido")
                    output_lines.append(f"\n--- 🏆 ➜ VENCEDOR ---")
                    output_lines.append(f"🥇 {winner_name}")
                break


            if i not in matches_by_round:
                continue

            output_lines.append(f"\n--- Rodada {i} ---")
            for match in matches_by_round[i]:
                p1_id = match['player1_id']
                p2_id = match['player2_id']
                winner_id = match['winner_id']

                p1_name = player_names.get(p1_id, f"ID: {p1_id[:4]}..")
                
                if p2_id:
                    p2_name = player_names.get(p2_id, f"ID: {p2_id[:4]}..")
                    line = f"{p1_name} vs {p2_name}"
                else: # Bye or TBA
                    # Checa se é um bye da rodada 1
                    if match['status'] == 'finished' and p1_id == winner_id:
                        line = f"{p1_name} (Bye)"
                    else:
                        line = f"{p1_name} vs (Aguardando)"

                if winner_id:
                    winner_name = player_names.get(winner_id, "Vencedor")
                    line += f"  -> 👑 {winner_name}"
                
                output_lines.append(line)

        return "\n".join(output_lines)



async def setup(bot: commands.Bot):
    await bot.add_cog(OfficialTournament(bot))