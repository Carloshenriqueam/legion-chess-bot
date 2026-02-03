# cogs/chess.py
import discord
from discord import app_commands
from discord.ext import commands, tasks as discord_tasks
from discord.ui import View, Button
import database
import lichess_api  # Importa o novo módulo
import elo_calculator
import tasks
import discord.utils
import asyncio
import urllib.parse
import logging
import asyncio
import re
from typing import Optional # Add this import here
import stockfish_analysis
from datetime import datetime

# Importar configurações de achievements de statistics.py
from cogs.statistics import ACHIEVEMENTS_CONFIG, HistoryView, get_mode_emoji
from typing import Optional

logger = logging.getLogger(__name__)

def _extract_game_id(game_url: str) -> Optional[str]:
    """Extrai o ID da partida de uma URL do Lichess."""
    # Pattern for typical Lichess game URLs
    match = re.search(r"lichess\.org/([a-zA-Z0-9]{8})", game_url)
    if match:
        return match.group(1)
    
    # Pattern for URLs with analysis paths, e.g., /analysis/standard/...
    match = re.search(r"lichess\.org/([a-zA-Z0-9]{8})", game_url)
    if match:
        return match.group(1)
        
    return None

# --- VIEW DO PERFIL ATUALIZADA ---
class PerfilView(View):
    def __init__(self, bot: commands.Bot, author_id: int, target_id: str):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        self.target_id = target_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Você não pode interagir com este perfil.", ephemeral=True)
            return False
        return True

    async def show_main_profile(self, interaction: discord.Interaction):
        player = await database.get_all_player_stats(self.target_id)
        if not player:
            embed = discord.Embed(title="❌ Erro", description="Jogador não encontrado mais.", color=0xCD0000)
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
            return

        user = await self.bot.fetch_user(self.target_id)
        profile_icon_url = "https://cdn.discordapp.com/attachments/1393788085455687802/1393788260295245844/logo_-_Copia.png?ex=69061fb8&is=6904ce38&hm=3f616afc5524c5d8d113f9202eda764a76b0a9dfbd555cd73963e97818e262a6&"

        embed = discord.Embed(
            title="📊 ➜ Perfil Geral",
            description=f"Estatísticas completas de **{user.display_name}**.",
            color=0xCD0000
        )
        
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=profile_icon_url)

        embed.add_field(
            name="🏆 ➜ Ratings",
            value=f"<:bullet:1434606387392020500> **Bullet:** `{player['rating_bullet']}` | "
                  f"<:blitz:1434606379720511619> **Blitz:** `{player['rating_blitz']}` | \n"
                  f"<:rapidas:1434606383092990124> **Rapid:** `{player['rating_rapid']}` | "
                  f"<:classica:1434609383202881778> **Clássico:** `{player['rating_classic']}`",
            inline=False
        )

        total_games = sum([
            player[f'wins_{m}'] + player[f'losses_{m}'] + player[f'draws_{m}']
            for m in ['bullet', 'blitz', 'rapid', 'classic']
        ])
        overall_win_rate = 0
        if total_games > 0:
            total_wins = sum(player[f'wins_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])
            overall_win_rate = (total_wins / total_games * 100)

        progress_bar_length = 15
        filled_blocks = int(round(overall_win_rate / 100 * progress_bar_length))
        empty_blocks = progress_bar_length - filled_blocks
        progress_bar = "█" * filled_blocks + "░" * empty_blocks

        embed.add_field(
            name="📈 ➜ Visão Geral",
            value=f"**Partidas Totais:** `{total_games}`\n"
                  f"**Taxa de Vitória:** `{progress_bar}` `{overall_win_rate:.1f}%`",
            inline=False
        )

        embed.add_field(
            name="🏅 ➜ Desempenho Interno",
            value=f"**✅ Vitórias:** `{sum(player[f'wins_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}` | "
                  f"**❌ Derrotas:** `{sum(player[f'losses_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}` | "
                  f"**🤝 Empates:** `{sum(player[f'draws_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}`",
            inline=False
        )
        
        
        
        
        try:
            achievements = await database.get_player_achievements(self.target_id)
            if achievements:
                badges_list = []
                for ach in achievements:
                    config = ACHIEVEMENTS_CONFIG.get(ach['achievement_type'])
                    if config and 'name' in config:
                        emoji = config['name'].split(' ')[0]
                        badges_list.append(emoji)
                    else:
                        badges_list.append('🏅')
                badges_str = " ".join(badges_list)
                if badges_str:
                    embed.add_field(name="🎖️ ➜ Achievements", value=badges_str, inline=False)
        except Exception as e:
            logger.warning(f"Não foi possível buscar achievements para o perfil de {self.target_id}: {e}")

        if player['lichess_username']:
            embed.add_field(name="", value=f"<:perfil:1434606210212036819> [{player['lichess_username']}](https://lichess.org/@/{player['lichess_username']})", inline=False)

        embed.set_footer(text=f"ID do Usuário: {self.target_id} | Use os botões para ver os detalhes de cada modo.")
        
        await interaction.response.edit_message(embed=embed, view=self)

    async def show_detailed_profile(self, interaction: discord.Interaction, mode: str):
        player = await database.get_all_player_stats(self.target_id)
        if not player:
            embed = discord.Embed(title="❌ Erro", description="Jogador não encontrado mais.", color=0xCD0000)
            await interaction.response.edit_message(embed=embed, view=None)
            self.stop()
            return

        rating_col = f'rating_{mode}'
        wins_col = f'wins_{mode}'
        losses_col = f'losses_{mode}'
        draws_col = f'draws_{mode}'

        wins = player[wins_col]
        losses = player[losses_col]
        draws = player[draws_col]
        total_games_mode = wins + losses + draws
        win_rate = (wins / total_games_mode * 100) if total_games_mode > 0 else 0

        mode_colors = {
            "bullet": 0xE74C3C,  # Vermelho
            "blitz": 0xF39C12,   # Laranja
            "rapid": 0x3498DB,   # Azul
            "classic": 0x9B59B6  # Roxo
        }
        embed_color = mode_colors.get(mode, discord.Color.gold())

        user = await self.bot.fetch_user(self.target_id)
        chess_icon_url = "https://cdn.discordapp.com/attachments/1393788085455687802/1393788260295245844/logo_-_Copia.png?ex=69037cb8&is=69022b38&hm=62cd1c9fced3697cf328ae4962f8f874f6317b5cb4df86a6471359ee06094d27&"

        embed = discord.Embed(
            title=f"🏆 ➜ Estatísticas de {mode.capitalize()}",
            description=f"Um resumo do desempenho de **{user.display_name}** nesta modalidade.",
            color=0xCD0000
        )
        
        embed.set_thumbnail(url=chess_icon_url)
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)

        embed.add_field(
            name="⭐ ➜ Visão Geral",
            value=f"**Rating Atual:** `{player[rating_col]}`\n"
                  f"**Partidas Jogadas:** `{total_games_mode}`\n"
                  f"**Taxa de Vitória:** `{win_rate:.1f}%`",
            inline=False
        )
        
        progress_bar_length = 15
        filled_blocks = int(round(win_rate / 100 * progress_bar_length))
        empty_blocks = progress_bar_length - filled_blocks
        progress_bar = "█" * filled_blocks + "░" * empty_blocks
        
        embed.add_field(
            name="🏅 ➜ Desempenho Detalhado",
            value=f"**Vitórias:** `{wins}` | **Derrotas:** `{losses}` | **Empates:** `{draws}`\n"
                  f"**Win Rate:** `{progress_bar}` `{win_rate:.1f}%`",
            inline=False
        )
        
        embed.set_footer(text=f"ID do Jogador: {self.target_id} | Use os botões para navegar.")
        
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Bullet", style=discord.ButtonStyle.grey, custom_id="perfil_bullet", row=0)
    async def bullet_button(self, interaction: discord.Interaction, button: Button):
        await self.show_detailed_profile(interaction, "bullet")

    @discord.ui.button(label="Blitz", style=discord.ButtonStyle.grey, custom_id="perfil_blitz", row=0)
    async def blitz_button(self, interaction: discord.Interaction, button: Button):
        await self.show_detailed_profile(interaction, "blitz")
        
    @discord.ui.button(label="Rapid", style=discord.ButtonStyle.grey, custom_id="perfil_rapid", row=0)
    async def rapid_button(self, interaction: discord.Interaction, button: Button):
        await self.show_detailed_profile(interaction, "rapid")

    @discord.ui.button(label="Clássico", style=discord.ButtonStyle.grey, custom_id="perfil_classic", row=0)
    async def classic_button(self, interaction: discord.Interaction, button: Button):
        await self.show_detailed_profile(interaction, "classic")

    @discord.ui.button(label="Voltar", style=discord.ButtonStyle.blurple, custom_id="perfil_back", row=1)
    async def back_button(self, interaction: discord.Interaction, button: Button):
        await self.show_main_profile(interaction)

    @discord.ui.button(label="Histórico", style=discord.ButtonStyle.primary, custom_id="perfil_history", row=1)
    async def history_button(self, interaction: discord.Interaction, button: Button):
        history_view = HistoryView(self.bot, self.author_id, self.target_id, page=0)
        await history_view.show_history(interaction, is_new_message=True)

    @discord.ui.button(label="Fechar", style=discord.ButtonStyle.danger, custom_id="perfil_close", row=1)
    async def close_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        try:
            # Prefer deleting the message that contains the view (component message)
            if interaction.message:
                await interaction.message.delete()
            else:
                # Fallback to deleting the original interaction response
                await interaction.delete_original_response()
        except discord.NotFound:
            # Message already deleted - ignore
            logger.debug("Mensagem de perfil já removida ao clicar em Fechar.")
        except Exception as e:
            # Log other issues but do not raise to avoid crashing the view scheduler
            logger.warning(f"Erro ao tentar remover mensagem de perfil: {e}")
        finally:
            self.stop()


# --- VIEW PARA RESPOSTA DE DESAFIO ---
class ChallengeResponseView(View):
    def __init__(self, bot: commands.Bot, challenge_id: int, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.challenge_id = challenge_id
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Verifica se o usuário é o desafiado
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.response.send_message('❌ Desafio não encontrado.', ephemeral=True)
            return False

        user_id = str(interaction.user.id)
        if user_id != challenge['challenged_id']:
            await interaction.response.send_message('❌ Você não pode responder este desafio!', ephemeral=True)
            return False

        return True

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.green, custom_id="accept_challenge")
    async def accept_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()

        # Busca o desafio
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.followup.send('❌ Desafio não encontrado.', ephemeral=True)
            return

        if challenge['status'] != 'pending':
            await interaction.followup.send('❌ Este desafio já foi respondido!', ephemeral=True)
            return

        # Aceita o desafio
        success = await self._accept_challenge(challenge, interaction)

        if success:
            # Desabilita os botões
            for child in self.children:
                child.disabled = True
            
            # Edita a mensagem original
            if self.message:
                try:
                    await self.message.edit(view=self)
                except:
                    pass

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.red, custom_id="decline_challenge")
    async def decline_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()

        # Busca o desafio
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.followup.send('❌ Desafio não encontrado.', ephemeral=True)
            return

        if challenge['status'] != 'pending':
            await interaction.followup.send('❌ Este desafio já foi respondido!', ephemeral=True)
            return

        # Recusa o desafio
        await database.update_challenge_status(self.challenge_id, 'declined')
        logger.info(f"❌ Desafio {self.challenge_id} recusado por {interaction.user.name}")

        # Desabilita os botões
        for child in self.children:
            child.disabled = True
        
        # Edita a mensagem original
        if self.message:
            try:
                await self.message.edit(view=self)
            except:
                pass

        await interaction.followup.send('❌ Desafio recusado!', ephemeral=True)

    async def _accept_challenge(self, challenge, interaction):
        """Aceita o desafio e cria a partida no Lichess."""
        challenger_id = challenge['challenger_id']
        challenged_id = challenge['challenged_id']
        time_control = challenge['time_control']

        # Busca usernames do Lichess
        challenger = await database.get_all_player_stats(challenger_id)
        challenged = await database.get_all_player_stats(challenged_id)

        if not challenger or not challenged:
            await interaction.followup.send('❌ Erro: jogadores não encontrados.', ephemeral=True)
            return False

        challenger_lichess = challenger.get('lichess_username')
        challenged_lichess = challenged.get('lichess_username')

        if not challenger_lichess or not challenged_lichess:
            await interaction.followup.send('❌ Erro: contas Lichess não vinculadas.', ephemeral=True)
            return False

        # Cria a partida no Lichess
        game_url = await lichess_api.create_lichess_game(time_control, rated=False)

        if not game_url:
            await interaction.followup.send('❌ Erro ao criar a partida no Lichess. Tente novamente.', ephemeral=True)
            return False

        # Atualiza o desafio com a URL da partida
        await database.update_challenge_game_url(self.challenge_id, game_url)
        await database.update_challenge_status(self.challenge_id, 'accepted')

        logger.info(f"✅ Desafio {self.challenge_id} aceito! Partida criada: {game_url}")

        # Busca usuários do Discord
        challenger_user = await self.bot.fetch_user(int(challenger_id))
        challenged_user = await self.bot.fetch_user(int(challenged_id))

        # Cria o embed para resposta efêmera
        is_rated = challenge.get('is_rated', False)
        challenger_mention = challenger_user.mention
        challenged_mention = challenged_user.mention

        embed = discord.Embed(title="✅ Desafio Aceito!", description="Uma partida foi criada! Clique no link para jogar.", color=0xCD0000)
        embed.add_field(name="Jogadores", value=f"{challenger_mention} vs {challenged_mention}", inline=False)
        embed.add_field(name="Modo de Jogo", value=f"⏱️ {time_control} | Rating Interno: {'Sim' if is_rated else 'Não'}", inline=True)
        embed.add_field(name="Acessar Partida", value=f"[Clique aqui para jogar]({game_url})", inline=True)
        embed.set_footer(text="Quando a partida terminar, clique no botão 'Finalizar' para processar o resultado.")

        # Cria a view com o botão de finalização
        view_challenger = GameFinishView(self.bot, self.challenge_id)
        view_challenged = GameFinishView(self.bot, self.challenge_id)

        # Envia DM para ambos os jogadores com o embed e o botão
        try:
            dm_message = await challenger_user.send(embed=embed, view=view_challenger)
            view_challenger.message = dm_message
            logger.info(f"📨 DM enviada para desafiante {challenger_user.name}")
        except discord.Forbidden:
            logger.warning(f"📨 Não foi possível enviar DM para {challenger_user.name}")

        try:
            dm_message = await challenged_user.send(embed=embed, view=view_challenged)
            view_challenged.message = dm_message
            logger.info(f"📨 DM enviada para desafiado {challenged_user.name}")
        except discord.Forbidden:
            logger.warning(f"📨 Não foi possível enviar DM para {challenged_user.name}")

        # Confirmação efêmera para quem aceitou
        await interaction.followup.send('✅ Desafio aceito! Verifique sua DM para acessar a partida.', ephemeral=True)

        logger.info(f"✅ Desafio {self.challenge_id} aceito! Partida criada: {game_url}")
        return True

    async def on_timeout(self):
        """Chamado quando o view expira (1 minuto sem resposta)."""
        challenge = await database.get_challenge(self.challenge_id)
        if challenge and challenge['status'] == 'pending':
            await database.update_challenge_status(self.challenge_id, 'expired')
            logger.info(f"⏰ Desafio {self.challenge_id} expirou após 1 minuto sem resposta")

            # Tenta editar a mensagem para mostrar que expirou
            if self.message:
                try:
                    embed = self.message.embeds[0]
                    embed.set_footer(text="⏰ Este desafio expirou.")
                    for child in self.children:
                        child.disabled = True
                    await self.message.edit(embed=embed, view=self)
                except:
                    pass


class PendingChallengesView(View):
    def __init__(self, bot: commands.Bot, user_id: str, pending_challenges: list):
        super().__init__(timeout=300)  # 5 minutos
        self.bot = bot
        self.user_id = user_id
        self.pending_challenges = pending_challenges

    async def setup_buttons(self):
        """Configura os botões dinamicamente após a inicialização."""
        # Adiciona botões dinamicamente para cada desafio
        for i, challenge in enumerate(self.pending_challenges[:5]):  # Limita a 5 desafios para não exceder limite de botões
            # Determina o oponente
            if challenge['challenger_id'] == self.user_id:
                opponent_id = challenge['challenged_id']
                action = "recusar"
            else:
                opponent_id = challenge['challenger_id']
                action = "cancelar"

            # Cria botão com ID do oponente (buscaremos o nome depois)
            button_label = f"❌ {action.capitalize()} Desafio #{challenge['id']}"
            button = Button(
                label=button_label,
                style=discord.ButtonStyle.red,
                custom_id=f"decline_challenge_{challenge['id']}"
            )
            button.callback = self.create_decline_callback(challenge['id'], action, opponent_id)
            self.add_item(button)

    def create_decline_callback(self, challenge_id: int, action: str, opponent_id: str):
        async def decline_callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("❌ Você não pode interagir com estes desafios!", ephemeral=True)
                return

            # Verifica se o desafio ainda existe e está pendente
            challenge = await database.get_challenge(challenge_id)
            if not challenge:
                await interaction.response.send_message('❌ Desafio não encontrado.', ephemeral=True)
                return

            if challenge['status'] != 'pending':
                await interaction.response.send_message('❌ Este desafio já foi resolvido.', ephemeral=True)
                return

            # Recusa/cancela o desafio
            await database.update_challenge_status(challenge_id, 'declined')

            # Notifica o outro jogador - REMOVIDO: nenhum resultado vai para DM
            # try:
            #     other_player = await self.bot.fetch_user(int(opponent_id))
            #     await other_player.send(f"⚔️ {interaction.user.mention} {action}elou o desafio #{challenge_id}.")
            # except Exception as e:
            #     logger.warning(f"Não foi possível notificar o outro jogador: {e}")

            await interaction.response.send_message(f'✅ Desafio #{challenge_id} foi {action}ado com sucesso!', ephemeral=True)

            # Remove o desafio da lista e atualiza a view
            self.pending_challenges = [c for c in self.pending_challenges if c['id'] != challenge_id]

            # Se não há mais desafios, desabilita todos os botões
            if not self.pending_challenges:
                for item in self.children:
                    item.disabled = True

        return decline_callback
class IndividualChallengeView(View):
    def __init__(self, bot: commands.Bot, user_id: str, challenge: dict):
        super().__init__(timeout=300)  # 5 minutos
        self.bot = bot
        self.user_id = user_id
        self.challenge = challenge

    async def setup_button(self):
        """Configura o botão dinamicamente após a inicialização."""
        # Determina o oponente
        if self.challenge['challenger_id'] == self.user_id:
            opponent_id = self.challenge['challenged_id']
            action = "cancelar"
        else:
            opponent_id = self.challenge['challenged_id']
            action = "recusar"

        # Cria botão
        button_label = f"❌ {action.capitalize()} Desafio"
        button = Button(
            label=button_label,
            style=discord.ButtonStyle.red,
            custom_id=f"decline_individual_challenge_{self.challenge['id']}"
        )
        button.callback = self.create_decline_callback(action, opponent_id)
        self.add_item(button)

    def create_decline_callback(self, action: str, opponent_id: str):
        async def decline_callback(interaction: discord.Interaction):
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("❌ Você não pode interagir com este desafio!", ephemeral=True)
                return

            # Verifica se o desafio ainda existe e está pendente
            challenge = await database.get_challenge(self.challenge['id'])
            if not challenge:
                await interaction.response.send_message('❌ Desafio não encontrado.', ephemeral=True)
                return

            if challenge['status'] != 'pending':
                await interaction.response.send_message('❌ Este desafio já foi resolvido.', ephemeral=True)
                return

            # Recusa/cancela o desafio
            await database.update_challenge_status(self.challenge['id'], 'declined')

            # Notifica o outro jogador - REMOVIDO: nenhum resultado vai para DM
            # try:
            #     other_player = await self.bot.fetch_user(int(opponent_id))
            #     await other_player.send(f"⚔️ {interaction.user.mention} {action}elou o desafio #{self.challenge['id']}.")
            # except Exception as e:
            #     logger.warning(f"Não foi possível notificar o outro jogador: {e}")

            await interaction.response.send_message(f'✅ Desafio #{self.challenge["id"]} foi {action}ado com sucesso!', ephemeral=True)

            # Desabilita o botão na mensagem original
            for item in self.children:
                item.disabled = True

            # Tenta editar a mensagem original para mostrar que foi resolvido
            try:
                embed = interaction.message.embeds[0]
                embed.set_footer(text="✅ Este desafio foi resolvido.")
                await interaction.message.edit(embed=embed, view=self)
            except:
                pass

        return decline_callback
class ScheduledGameView(View):
    def __init__(self, bot: commands.Bot, challenge_id: int):
        super().__init__(timeout=None)  # Não expira
        self.bot = bot
        self.challenge_id = challenge_id

    @discord.ui.button(label="Entrar na Partida", style=discord.ButtonStyle.gray, custom_id="access_scheduled_game")
    async def access_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer(ephemeral=True)

        # Buscar desafio
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.followup.send('❌ Desafio não encontrado.', ephemeral=True)
            return

        if challenge['status'] != 'scheduled':
            # Se já foi ativado, mostrar novamente os detalhes da partida
            if challenge.get('game_url'):
                # Buscar usuários
                try:
                    challenger = await self.bot.fetch_user(int(challenge['challenger_id']))
                    challenged = await self.bot.fetch_user(int(challenge['challenged_id']))
                except discord.NotFound:
                    await interaction.followup.send('❌ Um dos jogadores não foi encontrado.', ephemeral=True)
                    return

                # Identificar oponente do usuário que clicou
                user_id = str(interaction.user.id)
                if user_id == challenge['challenger_id']:
                    opponent = challenged
                else:
                    opponent = challenger

                # Criar embed ephemeral para o usuário
                ephemeral_embed = discord.Embed(
                    title="🎯 ➜ Desafio Agendado Ativado!",
                    description="Sua partida agendada foi ativada e está pronta para jogar!",
                    color=0x27AE60
                )
                ephemeral_embed.add_field(
                    name="Detalhes:",
                    value=f"🎯 ➜ **Oponente:** {opponent.mention}\n"
                          f"⏱️ ➜ **Tempo:** {challenge['time_control']}\n"
                          f"🏆 ➜ **Rating:** {'Sim' if challenge.get('is_rated', False) else 'Não'}\n"
                          f"🔗 ➜ **Partida:** [Clique aqui para jogar]({challenge['game_url']})",
                    inline=False
                )
                ephemeral_embed.set_footer(text="Quando a partida terminar, clique no botão 'Finalizar' para processar o resultado.")

                # Criar view com botão de finalização
                finish_view = GameFinishView(self.bot, self.challenge_id)

                await interaction.followup.send(embed=ephemeral_embed, view=finish_view, ephemeral=True)
                return
            else:
                await interaction.followup.send('❌ Este desafio já foi ativado ou cancelado.', ephemeral=True)
                return

        # Verificar se usuário é um dos jogadores
        user_id = str(interaction.user.id)
        if user_id not in [challenge['challenger_id'], challenge['challenged_id']]:
            await interaction.followup.send('❌ Esta partida não é sua!', ephemeral=True)
            return

        # Verificar horário
        from datetime import datetime
        try:
            scheduled_time = datetime.fromisoformat(challenge['scheduled_at'])
        except ValueError:
            # Tentar formato alternativo
            scheduled_time = datetime.strptime(challenge['scheduled_at'], '%Y-%m-%d %H:%M:%S')

        now = datetime.now()

        if now < scheduled_time:
            remaining_seconds = (scheduled_time - now).total_seconds()
            remaining_minutes = int(remaining_seconds // 60)
            remaining_hours = int(remaining_minutes // 60)
            remaining_days = int(remaining_hours // 24)

            if remaining_days > 0:
                time_str = f"{remaining_days} dia(s), {remaining_hours % 24} hora(s)"
            elif remaining_hours > 0:
                time_str = f"{remaining_hours} hora(s), {remaining_minutes % 60} minuto(s)"
            else:
                time_str = f"{remaining_minutes} minuto(s)"

            await interaction.followup.send(
                f'⏰ ➜ Esta partida está agendada para {scheduled_time.strftime("%d/%m/%Y às %H:%M")}\n'
                f'Volte quando for o horário!',
                ephemeral=True
            )
            return

        # Está no horário ou passou - ativar a partida
        logger.info(f"🎯 Ativando desafio agendado ID {challenge['id']} via botão")

        # Criar partida no Lichess
        game_url = await lichess_api.create_lichess_game(challenge['time_control'], rated=False)

        if not game_url:
            error_reason = lichess_api.get_last_create_game_error()
            message = "❌ Falha ao gerar o link para a partida."
            if error_reason:
                message += f" Motivo: {error_reason}"
            await interaction.followup.send(message, ephemeral=True)
            return

        await database.update_challenge_game_url(self.challenge_id, game_url)
        await database.activate_scheduled_challenge(self.challenge_id)

        # Buscar usuários
        try:
            challenger = await self.bot.fetch_user(int(challenge['challenger_id']))
            challenged = await self.bot.fetch_user(int(challenge['challenged_id']))
        except discord.NotFound:
            await interaction.followup.send('❌ Um dos jogadores não foi encontrado.', ephemeral=True)
            return

        # Identificar oponente do usuário que clicou
        user_id = str(interaction.user.id)
        if user_id == challenge['challenger_id']:
            opponent = challenged
        else:
            opponent = challenger

        # Criar embed ephemeral para o usuário
        ephemeral_embed = discord.Embed(
            title="🎯 ➜ Desafio Agendado Ativado!",
            description="Seu desafio agendado foi ativado e está pronto para jogar!",
            color=0x27AE60
        )
        ephemeral_embed.add_field(
            name="Detalhes:",
            value=f"🎯 ➜ **Oponente:** {opponent.mention}\n"
                  f"⏱️ ➜ **Tempo:** {challenge['time_control']}\n"
                  f"🏆 ➜ **Rating:** {'Sim' if challenge.get('is_rated', False) else 'Não'}\n"
                  f"🔗 ➜ **Partida:** [Clique aqui para jogar]({game_url})",
            inline=False
        )
        ephemeral_embed.set_footer(text="Quando a partida terminar, clique no botão 'Finalizar' para processar o resultado.")

        # Criar view com botão de finalização
        finish_view = GameFinishView(self.bot, self.challenge_id)

        # Desabilitar o botão de acesso na mensagem original
        
        button.label = "Partida Ativada"
        button.style = discord.ButtonStyle.success

        # Atualizar a mensagem original (remover view)
        try:
            await interaction.edit_original_response(view=self)
        except:
            pass

        # Enviar embed ephemeral com o botão de finalização
        await interaction.followup.send(embed=ephemeral_embed, view=finish_view, ephemeral=True)

        logger.info(f"✅ Desafio agendado #{self.challenge_id} ativado com sucesso via botão")


# Set global para rastrear desafios já processados
_processed_challenges = set()

class GameFinishView(View):
    def __init__(self, bot: commands.Bot, challenge_id: int):
        super().__init__(timeout=None)  # Não expira
        self.bot = bot
        self.challenge_id = challenge_id
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Verifica se o usuário é um dos participantes do desafio
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.response.send_message('❌ Desafio não encontrado.', ephemeral=True)
            return False

        user_id = str(interaction.user.id)
        if user_id not in [challenge['challenger_id'], challenge['challenged_id']]:
            await interaction.response.send_message('❌ Você não pode finalizar este desafio!', ephemeral=True)
            return False

        return True

    @discord.ui.button(label="Finalizar Partida", style=discord.ButtonStyle.red, custom_id="finish_game")
    async def finish_button(self, interaction: discord.Interaction, button: Button):
        # Previne processamento duplicado globalmente
        if self.challenge_id in _processed_challenges:
            logger.warning(f"⚠️ Desafio {self.challenge_id} já foi processado globalmente, ignorando clique")
            await interaction.response.defer()
            return

        try:
            await interaction.response.defer()
        except discord.NotFound:
            # Interação já expirou ou é desconhecida, não podemos responder
            logger.warning(f"Interação expirada para desafio {self.challenge_id}")
            return

        # Marca como processado globalmente imediatamente
        _processed_challenges.add(self.challenge_id)

        # Desabilita o botão imediatamente para evitar cliques múltiplos
        button.disabled = True
        button.label = "Processando..."
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception as e:
                logger.warning(f"❌ Não foi possível desabilitar botão temporariamente: {e}")

        # Verifica se já foi processado
        challenge = await database.get_challenge(self.challenge_id)
        if not challenge:
            await interaction.followup.send('❌ Desafio não encontrado.', ephemeral=True)
            return

        if challenge['status'] == 'finished':
            await interaction.followup.send('❌ Este desafio já foi finalizado!', ephemeral=True)
            return

        # Processa o resultado
        import tasks
        success, rating_changes = await tasks.process_challenge_result(self.bot, challenge)

        if success:
            # Busca o desafio atualizado
            updated_challenge = await database.get_challenge(self.challenge_id)
            
            # Importar a função auxiliar de criação de embeds
            import tasks
            
            # Obter dados necessários para criar os embeds
            winner_id = updated_challenge.get('winner_id')
            loser_id = updated_challenge.get('loser_id')
            result = updated_challenge.get('result')
            
            logger.info(f"🔍 Dados do desafio finalizado: winner_id={winner_id}, loser_id={loser_id}, result={result}, is_rated={updated_challenge.get('is_rated')}")
            logger.info(f"🔍 Challenger: {updated_challenge['challenger_id']}, Challenged: {updated_challenge['challenged_id']}")
            logger.info(f"🔍 Final: winner={winner_id} ({'challenger' if winner_id == updated_challenge['challenger_id'] else 'challenged'}), loser={loser_id} ({'challenger' if loser_id == updated_challenge['challenger_id'] else 'challenged'})")
            if not winner_id:
                logger.warning(f"⚠️ winner_id é None, usando challenger como fallback")
                winner_id = updated_challenge['challenger_id']
            if not loser_id:
                logger.warning(f"⚠️ loser_id é None, usando challenged como fallback")
                loser_id = updated_challenge['challenged_id']
            
            # Obter outcome da partida (pode precisar buscar novamente)
            game_url = updated_challenge.get('game_url')
            if game_url:
                import lichess_api
                outcome = await lichess_api.get_game_outcome(game_url)
            else:
                outcome = {}
            
            # Obter dados dos jogadores
            challenger_id = updated_challenge['challenger_id']
            challenged_id = updated_challenge['challenged_id']
            
            def _get_players():
                conn = database.get_conn()
                cur = conn.cursor()
                p_white = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (outcome.get('players', {}).get('white', {}).get('username'),)).fetchone() if outcome.get('players', {}).get('white', {}).get('username') else None
                p_black = cur.execute("SELECT * FROM players WHERE lichess_username = ?", (outcome.get('players', {}).get('black', {}).get('username'),)).fetchone() if outcome.get('players', {}).get('black', {}).get('username') else None
                conn.close()
                return p_white, p_black
            
            p_white, p_black = await asyncio.to_thread(_get_players)
            
            # Converter para dict
            p_white = dict(p_white) if p_white else None
            p_black = dict(p_black) if p_black else None
            
            # Calcular mudanças de rating (simplificado - pode precisar ajustar)
            # rating_changes = None  # Por enquanto, não calcular rating changes aqui
            
            # Criar os embeds usando a função auxiliar
            logger.info(f"📊 Criando embeds com rating_changes: {rating_changes}")
            result_embeds = await tasks.create_result_embeds(self.bot, updated_challenge, outcome, winner_id, loser_id, result, rating_changes, p_white, p_black)
            logger.info(f"📊 Criados {len(result_embeds)} embeds")
            
            # Desabilita o botão
            button.disabled = True
            button.style = discord.ButtonStyle.danger
            
            # Envia uma nova mensagem na DM de ambos os jogadores com os resultados
            player_ids = [challenger_id, challenged_id]
            for player_id in player_ids:
                try:
                    player = await self.bot.fetch_user(int(player_id))
                    await player.send(embeds=result_embeds)
                    logger.info(f"📨 Resultado enviado na DM para {player.name}")
                except discord.Forbidden:
                    logger.warning(f"📨 Não foi possível enviar DM para {player_id}")
                except Exception as e:
                    logger.error(f"❌ Erro ao enviar resultado na DM para {player_id}: {e}")
            
            button.disabled = True
            button.style = discord.ButtonStyle.danger
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception as e:
                    logger.warning(f"❌ Não foi possível desabilitar botão: {e}")

            # Limpa o desafio do set de processados após sucesso
            asyncio.create_task(self._cleanup_processed_challenge())

        else:
            await interaction.followup.send('❌ A partida ainda não terminou ou houve um erro. Tente novamente mais tarde.', ephemeral=True)

    async def _cleanup_processed_challenge(self):
        """Limpa o desafio do set de processados após um delay."""
        await asyncio.sleep(300)  # 5 minutos
        _processed_challenges.discard(self.challenge_id)
        logger.debug(f"🧹 Desafio {self.challenge_id} removido do set de processados")


# --- CLASSE PRINCIPAL DO COG ---
class Chess(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        tasks.set_bot_instance(bot)

    # Removido o loop de verificação do cog, agora é feito em main.py

    @app_commands.command(name="registrar", description="Registra você no sistema de xadrez.")
    @app_commands.describe(lichess_username="Seu nome de usuário no Lichess (opcional).")
    async def registrar(self, interaction: discord.Interaction, lichess_username: str = None):
        """Registra você no sistema de xadrez."""
        await interaction.response.defer()

        discord_id = str(interaction.user.id)
        discord_username = str(interaction.user)

        if lichess_username:
            exists = await lichess_api.verify_user_exists(lichess_username)
            if not exists:
                await interaction.followup.send(f'❌ O usuário `{lichess_username}` não existe no Lichess!')
                return

        await database.register_player(discord_id, discord_username, lichess_username)

        if lichess_username:
            await interaction.followup.send(f'✅ Registrado com sucesso! Sua conta do Lichess **{lichess_username}** foi vinculada e verificada.')
        else:
            await interaction.followup.send(f'✅ Registrado com sucesso! Use `/registrar <seu_usuario_lichess>` para conectar sua conta do Lichess.')

    @app_commands.command(name="verificar-lichess", description="Verifica se sua conta Lichess está válida.")
    async def verificar_lichess(self, interaction: discord.Interaction):
        """Verifica se o username Lichess vinculado é válido."""
        await interaction.response.defer()

        discord_id = str(interaction.user.id)
        player = await database.get_all_player_stats(discord_id)

        if not player:
            await interaction.followup.send('❌ Você não está registrado! Use `/registrar` primeiro.')
            return

        lichess_username = player.get('lichess_username')
        if not lichess_username:
            await interaction.followup.send('❌ Você não tem uma conta Lichess vinculada. Use `/registrar <seu_usuario_lichess>` para conectar.')
            return

        exists = await lichess_api.verify_user_exists(lichess_username)
        if exists:
            await interaction.followup.send(f'✅ Sua conta Lichess **{lichess_username}** está verificada e válida!')
        else:
            await interaction.followup.send(f'❌ Sua conta Lichess **{lichess_username}** não foi encontrada no Lichess. Use `/registrar <novo_username>` para atualizar.')

    @app_commands.command(name="desafiar", description="Desafia outro jogador para uma partida.")
    @app_commands.describe(opponent="O jogador que você deseja desafiar.", mode="Modo de jogo.", time_control="O controle de tempo (ex: 10+0).", valer_rating="A partida valerá rating interno?")
    @app_commands.choices(mode=[
        app_commands.Choice(name="Bullet", value="bullet"),
        app_commands.Choice(name="Blitz", value="blitz"),
        app_commands.Choice(name="Rapid", value="rapid"),
        app_commands.Choice(name="Classic", value="classic")
    ])
    async def desafiar(self, interaction: discord.Interaction, opponent: discord.Member, mode: str, time_control: str, valer_rating: bool):
        """Desafia outro jogador para uma partida."""

        await interaction.response.defer()

        challenger_id = str(interaction.user.id)
        challenged_id = str(opponent.id)
        channel_id = str(interaction.channel_id)

        logger.info(f"🔄 Novo desafio: {challenger_id} vs {challenged_id} | Tempo: {time_control} | Rating: {valer_rating}")

        # Validação básica: não desafiar a si mesmo
        if challenger_id == challenged_id:
            await interaction.followup.send('❌ Você não pode se desafiar!', ephemeral=True)
            return

        # Verificar se o oponente é um bot
        if opponent.bot:
            await interaction.followup.send('❌ Você não pode desafiar um bot!', ephemeral=True)
            return

        # Verificar se ambos estão registrados
        challenger = await database.get_all_player_stats(challenger_id)
        challenged = await database.get_all_player_stats(challenged_id)

        if not challenger:
            await interaction.followup.send('❌ Você precisa se registrar primeiro! Use `/registrar`', ephemeral=True)
            return
        if not challenged:
            await interaction.followup.send(f'❌ {opponent.mention} precisa se registrar primeiro com `/registrar`.', ephemeral=True)
            return

        # Verificar se ambos têm contas Lichess válidas
        challenger_lichess = challenger.get('lichess_username')
        challenged_lichess = challenged.get('lichess_username')

        if not challenger_lichess:
            await interaction.followup.send('❌ Você precisa vincular uma conta Lichess válida! Use `/registrar <seu_usuario_lichess>`', ephemeral=True)
            return
        if not challenged_lichess:
            await interaction.followup.send(f'❌ {opponent.mention} precisa vincular uma conta Lichess válida!', ephemeral=True)
            return

        # Verificar se as contas Lichess existem
        challenger_valid = await lichess_api.verify_user_exists(challenger_lichess)
        challenged_valid = await lichess_api.verify_user_exists(challenged_lichess)

        if not challenger_valid:
            await interaction.followup.send(f'❌ Sua conta Lichess `{challenger_lichess}` não é válida! Use `/registrar <novo_username>` para atualizar.', ephemeral=True)
            return
        if not challenged_valid:
            await interaction.followup.send(f'❌ A conta Lichess de {opponent.mention} não é válida!', ephemeral=True)
            return

        # Verificar se já existe desafio pendente entre os jogadores
        existing_challenge = await database.get_pending_challenge_between_players(challenger_id, challenged_id)
        if existing_challenge:
            await interaction.followup.send(f'❌ Já existe um desafio pendente entre vocês! ID: #{existing_challenge["id"]}', ephemeral=True)
            return

        # Verificar se algum dos jogadores já tem desafios pendentes ativos
        challenger_pending = await database.get_pending_challenges(challenger_id)
        challenged_pending = await database.get_pending_challenges(challenged_id)

        if challenger_pending:
            await interaction.followup.send('❌ Você já tem desafios pendentes! Resolva-os primeiro.', ephemeral=True)
            return
        if challenged_pending:
            await interaction.followup.send(f'❌ {opponent.mention} já tem desafios pendentes!', ephemeral=True)
            return

        # Validar time_control
        if not time_control or not isinstance(time_control, str):
            time_control = "10+0"

        # Validar se o time_control é compatível com o modo selecionado
        if not self._validate_time_control_for_mode(mode, time_control):
            embed = discord.Embed(
                title=f"❌ Time control inválido para o modo {mode.capitalize()}!",
                description=f"Controles válidos para {mode.capitalize()}:\n" +
                '\n'.join([f'• `{tc}`' for tc in {
                    "bullet": ["1+0", "1+1", "2+1"],
                    "blitz": ["3+0", "3+2", "5+0"],
                    "rapid": ["10+0", "15+10", "30+0"],
                    "classic": ["60+0", "90+30", "120+0"]
                }.get(mode, [])]),
                color=0xCD0000
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            return

        # Determinar time_control_mode baseado no time_control ou usar o mode fornecido
        if mode:
            time_control_mode = mode
            logger.info(f"📊 Mode fornecido: {mode}")
        else:
            time_control_mode = self._determine_time_control_mode(time_control)
            logger.info(f"📊 Time control: {time_control} -> Mode: {time_control_mode}")

        # Criar desafio
        challenge_id = await database.create_challenge(challenger_id, challenged_id, channel_id, time_control)

        # Definir se vale rating
        await database.set_challenge_rated(challenge_id, valer_rating)

        logger.info(f"✅ Desafio criado com sucesso! ID: {challenge_id}")

        embed = discord.Embed(
            title="⚔️ Novo Desafio!",
            description=f"{interaction.user.mention} desafiou {opponent.mention} para uma partida!",
            color=0xCD0000
        )
        embed.add_field(name="Detalhes do Desafio", value=f"⏱️ Tempo: {time_control} | 🏆 Rating: {'Sim' if valer_rating else 'Não'} | 🆔 ID: #{challenge_id}", inline=False)
        embed.set_footer(text=f"{opponent.display_name}, use /aceitar {challenge_id} ou /recusar {challenge_id}")

        # Criar view com botões
        view = ChallengeResponseView(self.bot, challenge_id)

        # Enviar mensagem com botões
        message = await interaction.followup.send(embed=embed, view=view)
        view.message = message

        # Tentar enviar DM para o oponente - REMOVIDO: nenhum resultado vai para DM
        # try:
        #     dm_message = f"⚔️ {interaction.user.name} te desafiou para uma partida de xadrez!\n"
        #     dm_message += f"⏱️ Tempo: {time_control} | 🏆 Rating: {'Sim' if valer_rating else 'Não'}\n"
        #     dm_message += f"Use os botões no canal ou `/aceitar {challenge_id}` ou `/recusar {challenge_id}` no servidor."
        #     await opponent.send(dm_message)
        #     logger.info(f"📨 DM enviada para {opponent.name}")
        # except discord.Forbidden:
        #     logger.warning(f"📨 Não foi possível enviar DM para {opponent.name} (DMs desabilitadas)")

        # Agendar expiração do desafio após 1 minuto
        self.bot.loop.create_task(self.expire_challenge_after_timeout(challenge_id, interaction.channel_id))

    def _validate_time_control_for_mode(self, mode: str, time_control: str) -> bool:
        """Valida se o time_control é válido para o modo selecionado."""
        valid_controls = {
            "bullet": ["1+0", "1+1", "2+1"],
            "blitz": ["3+0", "3+2", "5+0"],
            "rapid": ["10+0", "15+10", "30+0"],
            "classic": ["60+0", "90+30", "120+0"]
        }

        return time_control in valid_controls.get(mode, [])

    def _determine_time_control_mode(self, time_control: str) -> str:
        """Determina o modo do controle de tempo baseado na string."""
        try:
            # Formatos comuns: "10+0", "5+3", "15+10", etc.
            if "+" in time_control:
                initial_time, increment = time_control.split("+")
                initial_time = int(initial_time)
                increment = int(increment)

                # Lógica baseada em padrões comuns do Lichess
                if initial_time <= 1:
                    return "bullet"
                elif initial_time <= 10:
                    return "blitz"
                elif initial_time <= 30:
                    return "rapid"
                else:
                    return "classic"
            else:
                # Fallback para casos não padrão
                return "rapid"
        except (ValueError, AttributeError):
            logger.warning(f"Formato de time_control inválido: {time_control}, usando 'rapid' como fallback")
            return "rapid"

    async def expire_challenge_after_timeout(self, challenge_id: int, channel_id: str):
        """Expira um desafio após 1 minuto se ainda estiver pendente."""
        await asyncio.sleep(60)  # Espera 1 minuto

        # Verifica se o desafio ainda existe e está pendente
        challenge = await database.get_challenge(challenge_id)
        if not challenge or challenge['status'] != 'pending':
            return

        # Marca como expirado
        await database.update_challenge_status(challenge_id, 'expired')
        logger.info(f"⏰ Desafio {challenge_id} expirou após 1 minuto sem resposta")

        # Notifica no canal
        try:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                challenger = await self.bot.fetch_user(int(challenge['challenger_id']))
                challenged = await self.bot.fetch_user(int(challenge['challenged_id']))

                embed = discord.Embed(
                    title="⏰ Desafio Expirado!",
                    description=f"O desafio de {challenger.mention} para {challenged.mention} expirou após 1 minuto sem resposta.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Detalhes", value=f"⏱️ Tempo: {challenge['time_control']} | 🆔 ID: #{challenge_id}", inline=False)
                embed.set_footer(text="Desafios expiram automaticamente após 1 minuto.")

                await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Erro ao notificar expiração do desafio {challenge_id}: {e}")

    @app_commands.command(name="aceitar", description="Aceita um desafio de xadrez.")
    @app_commands.describe(challenge_id="O ID do desafio que você quer aceitar.")
    async def aceitar(self, interaction: discord.Interaction, challenge_id: int):
        """Aceita um desafio de xadrez e cria a partida no Lichess."""
        # Verificar se é DM
        if interaction.guild is None:
            await interaction.response.send_message('❌ Este comando só pode ser usado em servidores, não em DMs!', ephemeral=True)
            return
            
        challenged_id = str(interaction.user.id)
        
        challenge = await database.get_challenge(challenge_id)
        
        if not challenge:
            await interaction.response.send_message(f'❌ Desafio com ID `{challenge_id}` não encontrado.', ephemeral=True)
            return
            
        if str(challenge['challenged_id']) != challenged_id:
            await interaction.response.send_message('❌ Este desafio não é para você!', ephemeral=True)
            return

        if challenge['status'] == 'expired':
            await interaction.response.send_message('❌ Este desafio expirou! Você não pode mais aceitá-lo.', ephemeral=True)
            return
            
        if challenge['status'] != 'pending':
            await interaction.response.send_message(f'❌ Este desafio já foi {challenge["status"]}.', ephemeral=True)
            return

        await interaction.response.defer()

        is_rated = challenge.get('is_rated', False)

        # Cria uma URL de convite para a partida com o tempo de jogo correto
        # Partidas criadas no Lichess devem ser casuais; o rating interno é tratado separadamente.
        game_url = await lichess_api.create_lichess_game(
            challenge['time_control'],
            rated=False
        )

        if not game_url:
            error_reason = lichess_api.get_last_create_game_error()
            message = "❌ Falha ao gerar o link para a partida."
            if error_reason:
                message += f" Motivo: {error_reason}"
            await interaction.followup.send(message, ephemeral=True)
            return

        await database.update_challenge_game_url(challenge_id, game_url)
        await database.update_challenge_status(challenge_id, 'accepted')
        
        # Log para debug
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"✅ Desafio {challenge_id} aceito! Game URL: {game_url}")
        print(f"✅ Desafio {challenge_id} aceito! Game URL: {game_url}")
        
        try:
            challenger = await self.bot.fetch_user(challenge['challenger_id'])
            challenger_mention = challenger.mention
        except discord.NotFound:
            challenger_mention = "Um usuário desconhecido"

        embed = discord.Embed(title="✅ Desafio Aceito!", description="Uma partida foi criada! Clique no link para jogar.", color=0xCD0000)
        embed.add_field(name="Jogadores", value=f"{challenger_mention} vs {interaction.user.mention}", inline=False)
        embed.add_field(name="Modo de Jogo", value=f"⏱️ {challenge['time_control']} | Rating Interno: {'Sim' if is_rated else 'Não'}", inline=True)
        embed.add_field(name="Acessar Partida", value=f"[Clique aqui para jogar]({game_url})", inline=True)
        embed.set_footer(text="Quando a partida terminar, clique no botão 'Finalizar' para processar o resultado.")

        # Cria a view com o botão de finalização
        view_challenger = GameFinishView(self.bot, challenge_id)
        view_challenged = GameFinishView(self.bot, challenge_id)
        
        # Cria embed de confirmação
        confirm_embed = discord.Embed(
            title="✅ Desafio Aceito!",
            description="Uma partida foi criada! Clique no link para jogar.",
            color=0x00FF00
        )
        confirm_embed.add_field(name="Jogadores", value=f"{challenger_mention} vs {interaction.user.mention}", inline=False)
        confirm_embed.add_field(name="Modo de Jogo", value=f"⏱️ {challenge['time_control']} | Rating Interno: {'Sim' if is_rated else 'Não'}", inline=True)
        confirm_embed.add_field(name="Acessar Partida", value=f"[Clique aqui para jogar]({game_url})", inline=True)
        confirm_embed.set_footer(text="Quando a partida terminar, use /finalizar [id] para processar o resultado.")
        
        await interaction.followup.send(embed=confirm_embed, ephemeral=True)

        # Enviar DM para os jogadores com o embed e o botão - REMOVIDO: nenhum resultado vai para DM
        # try:
        #     dm_message = await challenger.send(embed=embed, view=view_challenger)
        #     view_challenger.message = dm_message
        # except discord.Forbidden:
        #     logger.warning(f"Não foi possível enviar DM para o desafiante {challenge['challenger_id']}")

        # try:
        #     dm_message = await interaction.user.send(embed=embed, view=view_challenged)
        #     view_challenged.message = dm_message
        # except discord.Forbidden:
        #     logger.warning(f"Não foi possível enviar DM para o desafiado {interaction.user.id}")

    @app_commands.command(name="recusar", description="Recusa um desafio de xadrez.")
    @app_commands.describe(challenge_id="O ID do desafio que você quer recusar.")
    async def recusar(self, interaction: discord.Interaction, challenge_id: int):
        """Recusa um desafio de xadrez."""
        challenged_id = str(interaction.user.id)
        
        challenge = await database.get_challenge(challenge_id)
        
        if not challenge:
            await interaction.response.send_message(f'❌ Desafio com ID `{challenge_id}` não encontrado.', ephemeral=True)
            return
            
        if str(challenge['challenged_id']) != challenged_id:
            await interaction.response.send_message('❌ Este desafio não é para você!', ephemeral=True)
            return

        if challenge['status'] == 'expired':
            await interaction.response.send_message('❌ Este desafio expirou! Você não precisa mais recusá-lo.', ephemeral=True)
            return
            
        if challenge['status'] != 'pending':
            await interaction.response.send_message(f'❌ Este desafio já foi {challenge["status"]}.', ephemeral=True)
            return

        await database.update_challenge_status(challenge_id, 'declined')
        
        try:
            challenger = await self.bot.fetch_user(challenge['challenger_id'])
            challenger_mention = challenger.mention
        except discord.NotFound:
            challenger_mention = "Um usuário desconhecido"

        await interaction.response.send_message(f"❌ {interaction.user.mention} recusou o desafio de {challenger_mention}.")

    @app_commands.command(name="atualizar-nome", description="Atualiza seu nome de usuário no banco de dados.")
    async def atualizar_nome(self, interaction: discord.Interaction):
        """Atualiza o nome de usuário no banco de dados para corresponder ao nome atual do Discord."""
        
        novo_nome = interaction.user.display_name
        await database.update_player_name(interaction.user.id, novo_nome)
        
        await interaction.response.send_message(
            f"✅ Seu nome de usuário foi atualizado para '{novo_nome}' no banco de dados.",
            ephemeral=True
        )

    @app_commands.command(name="perfil", description="Mostra o perfil de um jogador.")
    @app_commands.describe(jogador="O jogador cujo perfil você quer ver (deixe em branco para o seu).")
    async def perfil(self, interaction: discord.Interaction, jogador: discord.Member = None):
        """Mostra o perfil de um jogador."""
        target = jogador if jogador else interaction.user
        discord_id = str(target.id)
        
        player = await database.get_all_player_stats(discord_id)
        
        if not player:
            if target == interaction.user:
                await interaction.response.send_message('❌ Você ainda não está registrado! Use `/registrar` para começar.')
            else:
                await interaction.response.send_message(f'❌ {target.mention} ainda não está registrado!')
            return
        
        view = PerfilView(self.bot, interaction.user.id, discord_id)
        
        user = await self.bot.fetch_user(discord_id)
        profile_icon_url = "https://cdn.discordapp.com/attachments/1393788085455687802/1393788260295245844/logo_-_Copia.png?ex=69037cb8&is=69022b38&hm=62cd1c9fced3697cf328ae4962f8f874f6317b5cb4df86a6471359ee06094d27&"

        embed = discord.Embed(
            title="📊 ➜ Perfil Geral",
            description=f"Estatísticas completas de **{user.display_name}**.",
            color = 0xCD0000
        )
        
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
        embed.set_thumbnail(url=profile_icon_url)

        embed.add_field(
            name="🏆 ➜ Ratings",
            value=f"<:bullet:1434606387392020500> **Bullet:** `{player['rating_bullet']}` | "
                  f"<:blitz:1434606379720511619> **Blitz:** `{player['rating_blitz']}` | \n"
                  f"<:rapidas:1434606383092990124> **Rapid:** `{player['rating_rapid']}` | "
                  f"<:classica:1434609383202881778> **Clássico:** `{player['rating_classic']}`",
            inline=False
        )
        

        total_games = sum([
            player[f'wins_{m}'] + player[f'losses_{m}'] + player[f'draws_{m}']
            for m in ['bullet', 'blitz', 'rapid', 'classic']
        ])
        overall_win_rate = 0
        if total_games > 0:
            total_wins = sum(player[f'wins_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])
            overall_win_rate = (total_wins / total_games * 100)

        progress_bar_length = 15
        filled_blocks = int(round(overall_win_rate / 100 * progress_bar_length))
        empty_blocks = progress_bar_length - filled_blocks
        progress_bar = "█" * filled_blocks + "░" * empty_blocks

        embed.add_field(
            name="📈 ➜ Visão Geral",
            value=f"**Partidas Totais:** `{total_games}`\n"
                  f"**Taxa de Vitória:** `{progress_bar}` `{overall_win_rate:.1f}%`",
            inline=False
        )

        embed.add_field(
            name="📈 ➜ Desempenho Interno",
            value=f"**✅ Vitórias:** `{sum(player[f'wins_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}` | "
                  f"**❌ Derrotas:** `{sum(player[f'losses_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}` | "
                  f"**🤝 Empates:** `{sum(player[f'draws_{m}'] for m in ['bullet', 'blitz', 'rapid', 'classic'])}`",
            inline=False
        )
        try:
            achievements = await database.get_player_achievements(discord_id)
            if achievements:
                badges_list = []
                for ach in achievements:
                    config = ACHIEVEMENTS_CONFIG.get(ach['achievement_type'])
                    if config and 'name' in config:
                        emoji = config['name'].split(' ')[0]
                        badges_list.append(emoji)
                    else:
                        badges_list.append('🏅')
                badges_str = " ".join(badges_list)
                if badges_str:
                    embed.add_field(name="🏅 ➜ Achievements", value=badges_str, inline=False)
        except Exception as e:
            logger.warning(f"Não foi possível buscar achievements para o perfil de {discord_id}: {e}")
            
        if player['lichess_username']:
            embed.add_field(name="", value=f"<:perfil:1434606210212036819> [{player['lichess_username']}](https://lichess.org/@/{player['lichess_username']})", inline=False)

        embed.set_footer(text=f"ID do Usuário: {discord_id} | Use os botões para ver os detalhes de cada modo.")
        
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="agendar-partida", description="[ADMIN] Agenda um desafio programado entre dois jogadores.")
    @app_commands.describe(
        jogador1="Primeiro jogador da partida",
        jogador2="Segundo jogador da partida", 
        time_control="Controle de tempo (ex: 10+0)",
        rating_interno="A partida valerá rating interno?",
        data="Data e hora para jogar (formato: DD/MM/YYYY HH:MM)",
    )
    @app_commands.default_permissions(administrator=True)
    async def agendar(self, interaction: discord.Interaction, jogador1: discord.Member, jogador2: discord.Member, time_control: str, rating_interno: bool, data: str, canal: discord.TextChannel = None):
        """Agenda um desafio programado entre dois jogadores (apenas admins)."""
        await interaction.response.defer()

        # Verificar se é admin
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send('❌ Apenas administradores podem usar este comando!', ephemeral=True)
            return

        creator_id = str(interaction.user.id)
        player1_id = str(jogador1.id)
        player2_id = str(jogador2.id)
        channel_id = str(canal.id) if canal else str(interaction.channel_id)

        # Validações básicas
        if player1_id == player2_id:
            await interaction.followup.send('❌ Os jogadores devem ser diferentes!', ephemeral=True)
            return

        if jogador1.bot or jogador2.bot:
            await interaction.followup.send('❌ Não é possível agendar partidas com bots!', ephemeral=True)
            return

        # Verificar se ambos estão registrados
        player1_data = await database.get_all_player_stats(player1_id)
        player2_data = await database.get_all_player_stats(player2_id)

        if not player1_data:
            await interaction.followup.send(f'❌ {jogador1.mention} precisa se registrar primeiro! Use `/registrar`', ephemeral=True)
            return
        if not player2_data:
            await interaction.followup.send(f'❌ {jogador2.mention} precisa se registrar primeiro! Use `/registrar`', ephemeral=True)
            return

        # Verificar contas Lichess
        if not player1_data.get('lichess_username'):
            await interaction.followup.send(f'❌ {jogador1.mention} precisa vincular uma conta Lichess!', ephemeral=True)
            return
        if not player2_data.get('lichess_username'):
            await interaction.followup.send(f'❌ {jogador2.mention} precisa vincular uma conta Lichess!', ephemeral=True)
            return

        # Verificar se as contas Lichess existem
        player1_lichess = player1_data.get('lichess_username')
        player2_lichess = player2_data.get('lichess_username')

        player1_valid = await lichess_api.verify_user_exists(player1_lichess)
        player2_valid = await lichess_api.verify_user_exists(player2_lichess)

        if not player1_valid:
            await interaction.followup.send(f'❌ A conta Lichess `{player1_lichess}` de {jogador1.mention} não é válida! Peça para atualizar com `/registrar <novo_username>`', ephemeral=True)
            return
        if not player2_valid:
            await interaction.followup.send(f'❌ A conta Lichess `{player2_lichess}` de {jogador2.mention} não é válida! Peça para atualizar com `/registrar <novo_username>`', ephemeral=True)
            return

        # Validar formato da data
        try:
            from datetime import datetime
            scheduled_datetime = datetime.strptime(data, '%d/%m/%Y %H:%M')
            # Garantir que está no futuro
            now = datetime.now()
            if scheduled_datetime <= now:
                await interaction.followup.send('❌ A data deve ser no futuro!', ephemeral=True)
                return
            logger.info(f"📅 Data agendada: {scheduled_datetime}, Agora: {now}")
        except ValueError:
            await interaction.followup.send('❌ Formato de data inválido! Use: DD/MM/YYYY HH:MM (ex: 15/01/2026 14:30)', ephemeral=True)
            return

        # Validar time_control (usar a mesma lógica do desafiar)
        time_control_mode = self._determine_time_control_mode(time_control)
        if not self._validate_time_control_for_mode(time_control_mode, time_control):
            valid_controls = {
                "bullet": ["1+0", "1+1", "2+1"],
                "blitz": ["3+0", "3+2", "5+0"],
                "rapid": ["10+0", "15+10", "30+0"],
                "classic": ["60+0", "90+30", "120+0"]
            }
            await interaction.followup.send(
                f'❌ Time control inválido para o modo {time_control_mode.capitalize()}!\n'
                f'Controles válidos: {", ".join(valid_controls.get(time_control_mode, []))}',
                ephemeral=True
            )
            return

        # Criar desafio agendado
        scheduled_str = scheduled_datetime.strftime('%Y-%m-%dT%H:%M:%S')
        logger.info(f"📅 Criando desafio agendado para {scheduled_str}")
        challenge_id = await database.create_challenge(
            player1_id, player2_id, channel_id, time_control, 
            scheduled_str
        )
        logger.info(f"📅 Desafio criado com ID {challenge_id}, status deve ser 'scheduled'")

        # Definir se vale rating
        await database.set_challenge_rated(challenge_id, rating_interno)

        logger.info(f"📅 Desafio agendado criado! ID: {challenge_id} para {scheduled_datetime}")

        # Criar embed de confirmação
        embed = discord.Embed(
            title="📅 ➜ Desafio Agendado!",
            description=f"Um desafio foi agendado entre {jogador1.mention} e {jogador2.mention}",
            color=0xCD0000
        )
        embed.add_field(
            name="Detalhes:",
            value=f"⏱️ ➜ **Tempo:** {time_control}\n"
                  f"🏆 ➜ **Rating:** {'Sim' if rating_interno else 'Não'}\n"
                  f"📅 ➜ **Data:** {scheduled_datetime.strftime('%d/%m/%Y às %H:%M')}\n"
                  f"🆔 ➜ **ID:** #{challenge_id}",
            inline=False
        )
        if canal:
            embed.add_field(
                name="Canal",
                value=canal.mention,
                inline=True
            )
        embed.set_footer(text=f"Este desafio será ativado quando um dos jogadores clicar no botão 'Partida' no horário marcado.")

        # Criar view com botão de acesso
        access_view = ScheduledGameView(self.bot, challenge_id)

        await interaction.followup.send(embed=embed, view=access_view)

        # Se foi especificado um canal, enviar anúncio lá também
        if canal:
            channel_embed = discord.Embed(
                title="📅 ➜ Desafio Programado!",
                description=f"{jogador1.mention} vs {jogador2.mention}",
                color=0xCD0000
            )
            channel_embed.add_field(
                name="Detalhes:",
                value=f"⏱️ ➜ **Tempo:** {time_control}\n"
                      f"🏆 ➜ **Rating:** {'Sim' if rating_interno else 'Não'}\n"
                      f"📅 ➜ **Quando:** {scheduled_datetime.strftime('%d/%m/%Y às %H:%M')}",
                inline=False
            )
            channel_embed.set_footer(text="Os jogadores receberão acesso à partida no horário marcado.")
            
            try:
                await canal.send(embed=channel_embed)
            except discord.Forbidden:
                await interaction.followup.send('⚠️ Não foi possível enviar anúncio no canal especificado.', ephemeral=True)

    @app_commands.command(name="partidas-programadas", description="Mostra suas partidas programadas.")
    async def partidas_programadas(self, interaction: discord.Interaction):
        """Mostra as partidas programadas do usuário."""
        discord_id = str(interaction.user.id)
        
        challenges = await database.get_scheduled_challenges_for_player(discord_id)
        
        if not challenges:
            embed = discord.Embed(
                title="📅 ➜ Desafios Agendados",
                description="Você não tem desafios agendados.",
                color=0xCD0000
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title="📅 ➜ Seus Desafios Agendados",
            description=f"Encontrados {len(challenges)} desafio(s) agendado(s):",
            color=0xCD0000
        )

        for challenge in challenges:
            opponent = challenge['challenged_name'] if challenge['challenger_id'] == discord_id else challenge['challenger_name']
            embed.add_field(
                name=f"Desafio #{challenge['id']} - vs {opponent}",
                value=f"⏱️ **Tempo:** {challenge['time_control']}\n"
                      f"🏆 **Rating:** {'Sim' if challenge.get('is_rated', False) else 'Não'}\n"
                      f"📅 **Data:** {challenge['scheduled_at'][:16].replace('T', ' ')}",
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="desafios", description="Mostra seus desafios pendentes.")
    async def desafios(self, interaction: discord.Interaction):
        """Mostra seus desafios pendentes."""
        discord_id = str(interaction.user.id)

        # Busca desafios normais (não do torneio)
        pending = await database.get_pending_challenges(discord_id)

        # Busca desafios de torneio ativos
        tournament_challenges = []
        try:
            # Busca todos os torneios em andamento
            from database import get_tournament_matches
            tournaments = await database.get_open_tournaments()
            tournaments.extend(await database.get_tournaments_by_status('in_progress'))

            for tournament in tournaments:
                matches = await database.get_tournament_matches(tournament['id'])
                for match in matches:
                    if match['challenge_id'] and match['status'] == 'pending':
                        challenge = await database.get_challenge(match['challenge_id'])
                        if challenge and (challenge['challenger_id'] == discord_id or challenge['challenged_id'] == discord_id):
                            tournament_challenges.append({
                                'challenge': challenge,
                                'tournament': tournament,
                                'match': match
                            })
        except Exception as e:
            print(f"Erro ao buscar desafios de torneio: {e}")

        if not pending and not tournament_challenges:
            await interaction.response.send_message('📭 Você não tem desafios pendentes.')
            return

        # Envia mensagem inicial com cabeçalho
        header_embed = discord.Embed(
            title=f"⚔️ ➜ Desafios Pendentes de {interaction.user.name}",
            description="Cada desafio tem seu próprio botão de ação abaixo.",
            color=0xCD0000
        )

        if tournament_challenges:
            header_embed.add_field(
                name="🏆 ➜ Desafios de Torneio",
                value=f"Você tem {len(tournament_challenges)} desafio(s) de torneio pendente(s).\n"
                      "Os desafios de torneio são enviados diretamente no seu DM.",
                inline=False
            )

        await interaction.response.send_message(embed=header_embed, ephemeral=True)

        # Envia uma mensagem separada para cada desafio pendente
        for challenge in pending:
            # Busca informações dos jogadores
            challenger = await self.bot.fetch_user(int(challenge['challenger_id']))
            challenged = await self.bot.fetch_user(int(challenge['challenged_id']))

            # Determina se o usuário é desafiante ou desafiado
            is_challenger = challenge['challenger_id'] == discord_id
            opponent = challenged if is_challenger else challenger

            # Cria embed detalhado para o desafio
            challenge_embed = discord.Embed(
                title=f"🎯 ➜ Desafio #{challenge['id']}",
                description=f"**{challenger.mention}** desafiou **{challenged.mention}**",
                color=0xCD0000
            )

            challenge_embed.add_field(
                name="Detalhes:",
                value=f"⏱️ **Tempo:** {challenge['time_control']}\n"
                      f"🏆 **Rating:** {'Sim' if challenge.get('is_rated', False) else 'Não'}\n"
                      f"👤 **Oponente:** {opponent.mention}",
                inline=True
            )

            # Cria view individual para este desafio
            view = IndividualChallengeView(self.bot, discord_id, challenge)
            await view.setup_button()

            # Envia a mensagem com embed e botão
            await interaction.followup.send(embed=challenge_embed, view=view, ephemeral=True)

    @app_commands.command(name="puzzle-diario", description="Anuncia o puzzle de xadrez do dia (Apenas para admins).")
    @app_commands.default_permissions(administrator=True)
    async def puzzle_diario(self, interaction: discord.Interaction):
        """Anuncia o puzzle diário no canal."""
        await interaction.response.defer()

        puzzle_data = await lichess_api.get_daily_puzzle()

        if not puzzle_data:
            await interaction.followup.send("❌ Não foi possível buscar o puzzle diário do Lichess. Tente novamente mais tarde.")
            return

        await database.set_active_puzzle(puzzle_data)

        guild = interaction.guild
        role = discord.utils.get(guild.roles, name="😎 Membro")
        
        if role:
            content = f"{role.mention} 🧩 Novo puzzle de xadrez disponível!"
        else:
            content = "🧩 Novo puzzle de xadrez disponível! (Cargo 'membros' não foi encontrado para notificação)"
            print("AVISO: O cargo 'membros' não foi encontrado no servidor.")

        solution_length = len(puzzle_data['solution'])
        if solution_length == 1:
            move_text = "o melhor movimento"
            example = "Nf3"
        else:
            move_text = "a melhor sequência de movimentos"
            example = "Nf3 Nc6"

        embed = discord.Embed(
            title="🧩 Puzzle de Xadrez do Dia",
            description=f"**Encontre {move_text} para as {puzzle_data['color'].capitalize()}.**\n\nUse `/responder <movimento>` para enviar sua resposta. Ex: `/responder {example}`",
            color=0xCD0000
        )

        # Adicionar imagem do puzzle
        puzzle_image_url = f"https://lichess.org/export/fen.gif?fen={urllib.parse.quote(puzzle_data['fen'])}&color={puzzle_data['color']}&theme=blue&piece=cburnett"
        embed.set_image(url=puzzle_image_url)

        embed.add_field(
            name="Posição (PGN):",
            value=f"```{puzzle_data['pgn']}```",
            inline=False
        )
        embed.set_footer(text=f"Puzzle ID: {puzzle_data['puzzle_id']} | Fonte: Lichess")

        announcement_message = await interaction.followup.send(content=content, embed=embed)
        
        await database.set_active_puzzle(puzzle_data, str(announcement_message.id))

    @app_commands.command(name="check_games", description="Verifica manualmente partidas finalizadas (debug).")
    @app_commands.default_permissions(administrator=True)
    async def check_games_command(self, interaction: discord.Interaction):
        """Verifica manualmente partidas finalizadas para debug."""
        await interaction.response.defer()
        logger.info("🔄 Executando verificação manual de partidas...")
        await tasks.check_finished_games()
        await interaction.followup.send("✅ Verificação manual executada. Verifique o console para logs.")

    @app_commands.command(name="responder", description="Responde ao puzzle de xadrez do dia.")
    @app_commands.describe(resposta="O primeiro movimento da solução (ex: Nf3, e4, Qh5#)")
    async def responder(self, interaction: discord.Interaction, resposta: str):
        """Envia sua resposta para o puzzle do dia."""
        puzzle = await database.get_active_puzzle()

        if not puzzle:
            await interaction.response.send_message("❌ Não há nenhum puzzle ativo no momento.", ephemeral=True)
            return

        if puzzle['solved_by']:
            solver = await self.bot.fetch_user(int(puzzle['solved_by']))
            await interaction.response.send_message(f"🏁 Este puzzle já foi resolvido por {solver.mention}!", ephemeral=True)
            return

        user_move = resposta.strip().lower()
        correct_move = puzzle['first_move'].strip().lower()

        if user_move == correct_move:
            await database.mark_puzzle_as_solved(str(interaction.user.id))

            try:
                puzzle_message_id = puzzle.get('announcement_message_id')
                if puzzle_message_id:
                    channel = self.bot.get_channel(int(interaction.channel_id))
                    original_message = await channel.fetch_message(int(puzzle_message_id))
                    
                    solved_embed = original_message.embeds[0].copy()
                    solved_embed.title = "🧩 Puzzle Resolvido!"
                    solved_embed.description = f"Resolvido por: {interaction.user.mention}\n\n**Movimento Correto:** `{correct_move.upper()}`"
                    solved_embed.color = discord.Color.green()
                    
                    await original_message.edit(embed=solved_embed, view=None)
            except (discord.NotFound, discord.Forbidden, AttributeError):
                pass

            embed = discord.Embed(
                title="🎉 Resposta Correta!",
                description=f"Parabéns {interaction.user.mention}! Você resolveu o puzzle do dia.",
                color=0xCD0000
            )
            embed.add_field(name="Movimento Correto", value=f"**{correct_move.upper()}**", inline=False)
            embed.set_footer(text=f"Puzzle ID: {puzzle['puzzle_id']}")
            
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Resposta incorreta. Tente novamente!", ephemeral=True)

    @app_commands.command(name="debug-scheduled", description="[DEBUG] Verifica status dos desafios agendados.")
    async def debug_scheduled(self, interaction: discord.Interaction):
        """Comando de debug para verificar desafios agendados."""
        await interaction.response.defer(ephemeral=True)
        
        # Verificar próximos desafios
        def _query():
            conn = database.get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, challenger_id, challenged_id, scheduled_at, status
                FROM challenges
                WHERE status = 'scheduled'
                ORDER BY scheduled_at ASC
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        results = await asyncio.to_thread(_query)

        if results:
            response = f"📅 Encontrados {len(results)} desafios agendados:\n"
            for r in results:
                scheduled_time = datetime.fromisoformat(r['scheduled_at'])
                now = datetime.now()
                diff = (scheduled_time - now).total_seconds()
                status = "✅ No futuro" if diff > 0 else f"⚠️ Atrasado há {-diff:.1f}s"
                response += f"• ID {r['id']}: {r['scheduled_at']} - {status}\n"
        else:
            response = "📅 Nenhum desafio agendado encontrado"

        # Verificar se há desafios que deveriam ter sido ativados
        def _query_ready():
            conn = database.get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, challenger_id, challenged_id, scheduled_at, status
                FROM challenges
                WHERE status = 'scheduled'
                AND datetime(scheduled_at) <= datetime('now')
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        ready_results = await asyncio.to_thread(_query_ready)

        if ready_results:
            response += f"\n⚠️ **{len(ready_results)} desafios atrasados** que deveriam ter sido ativados:\n"
            for r in ready_results:
                scheduled_time = datetime.fromisoformat(r['scheduled_at'])
                now = datetime.now()
                diff = (now - scheduled_time).total_seconds()
                response += f"• ID {r['id']}: atrasado há {diff:.1f} segundos\n"

        await interaction.followup.send(response, ephemeral=True)

    @app_commands.command(name="ativar-atrasados", description="[ADMIN] Ativa desafios agendados atrasados.")
    async def ativar_atrasados(self, interaction: discord.Interaction):
        """Ativa manualmente desafios agendados que estão atrasados."""
        await interaction.response.defer(ephemeral=True)
        
        # Verificar se é admin
        if not interaction.user.guild_permissions.administrator:
            await interaction.followup.send('❌ Apenas administradores podem usar este comando!', ephemeral=True)
            return

        # Buscar desafios atrasados
        def _query_ready():
            conn = database.get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, challenger_id, challenged_id, scheduled_at, status
                FROM challenges
                WHERE status = 'scheduled'
                AND datetime(scheduled_at) <= datetime('now')
            """)
            results = cursor.fetchall()
            conn.close()
            return results

        ready_results = await asyncio.to_thread(_query_ready)

        if not ready_results:
            await interaction.followup.send("✅ Nenhum desafio atrasado encontrado!", ephemeral=True)
            return

        activated_count = 0
        failed_count = 0

        for challenge_data in ready_results:
            try:
                # Converter para dict
                challenge = dict(challenge_data)
                logger.info(f"🎯 Ativando desafio atrasado ID {challenge['id']}")
                
                # Ativar o desafio
                import tasks
                success = await tasks.start_scheduled_challenge(self.bot, challenge)
                
                if success:
                    activated_count += 1
                    logger.info(f"✅ Desafio ID {challenge['id']} ativado com sucesso")
                else:
                    failed_count += 1
                    logger.error(f"❌ Falha ao ativar desafio ID {challenge['id']}")
                    
            except Exception as e:
                failed_count += 1
                logger.error(f"Erro ao ativar desafio ID {challenge['id']}: {e}")

        response = f"🎯 Ativação concluída:\n✅ {activated_count} desafios ativados\n❌ {failed_count} falhas"
        await interaction.followup.send(response, ephemeral=True)


# Função necessária para carregar o Cog
async def setup(bot: commands.Bot):
    await bot.add_cog(Chess(bot))
    print("[LOG] Chess cog carregado com 15 comandos.")
