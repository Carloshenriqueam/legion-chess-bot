import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View
import database
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

ACHIEVEMENTS_CONFIG = {
    'default': {
        'name': '<:verified:1446673529989890168> Membro Verificado',
        'description': 'Se registrou no bot'
    },
    'first_win': {
        'name': '🎯 Primeira Vitória',
        'description': 'Vença sua primeira partida'
    },
    'win_streak_3': {
        'name': '🔥 Win Streak 3',
        'description': 'Vença 3 partidas consecutivas'
    },
    'win_streak_5': {
        'name': '🌟 Win Streak 5',
        'description': 'Vença 5 partidas consecutivas'
    },
    'rating_1500': {
        'name': '⭐ Rating 1500+',
        'description': 'Atinja rating de 1500 ou mais'
    },
    'rating_1800': {
        'name': '👑 Rating 1800+',
        'description': 'Atinja rating de 1800 ou mais'
    },
    'tournament_winner': {
        'name': '<:champion:1446676107029123163> Campeão',
        'description': 'Vença um torneio'
    },
    'head_to_head_5': {
        'name': '<:rival:446673678749405377> Rival',
        'description': 'Jogue 5 partidas contra o mesmo adversário'
    }
}

def get_mode_emoji(mode: str) -> str:
    """Retorna emoji para cada modo de jogo."""
    emojis = {
        'bullet': '<:bullet:1434606387392020500>',
        'blitz': '<:blitz:1434606379720511619>',
        'rapid': '<:rapidas:1434606383092990124>',
        'classic': '<:classica:1434609383202881778>'
    }
    return emojis.get(mode, '♟️')

class HistoryView(View):
    def __init__(self, bot: commands.Bot, author_id: int, target_id: str, page: int = 0):
        super().__init__(timeout=300)
        self.bot = bot
        self.author_id = author_id
        self.target_id = target_id
        self.page = page
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Você não pode interagir com este histórico.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⬅️ Anterior", custom_id="history_prev", style=discord.ButtonStyle.secondary)
    async def history_prev(self, interaction: discord.Interaction, button: Button):
        self.page = max(0, self.page - 1)
        await self.show_history(interaction)

    @discord.ui.button(label="Próxima ➡️", custom_id="history_next", style=discord.ButtonStyle.secondary)
    async def history_next(self, interaction: discord.Interaction, button: Button):
        self.page += 1
        await self.show_history(interaction)

    @discord.ui.button(label="Fechar", custom_id="history_close", style=discord.ButtonStyle.danger)
    async def history_close(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        await interaction.delete_original_response()
        self.stop()

    async def show_history(self, interaction: discord.Interaction, is_new_message: bool = False):
        games = await database.get_player_game_history(self.target_id, limit=50)
        
        if not games:
            embed = discord.Embed(
                title="📋 Histórico de Partidas",
                description="Nenhuma partida registrada ainda.",
                color=discord.Color.greyple()
            )
            if is_new_message:
                await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
            else:
                await interaction.response.edit_message(embed=embed, view=self)
            return
        
        try:
            user = await self.bot.fetch_user(int(self.target_id))
            display_name = user.display_name
        except:
            display_name = "Jogador"
        
        items_per_page = 5
        start = self.page * items_per_page
        end = start + items_per_page
        page_games = games[start:end]
        
        embed = discord.Embed(
            title=f"📋 Histórico de Partidas - {display_name}",
            description=f"Mostrando {start + 1}-{min(end, len(games))} de {len(games)} partidas",
            color=discord.Color.blue()
        )
        
        for game in page_games:
            opponent_id = game['player2_id'] if game['player1_id'] == self.target_id else game['player1_id']
            opponent_name = game['player2_name'] if game['player1_id'] == self.target_id else game['player1_name']
            
            try:
                opponent = await self.bot.fetch_user(int(opponent_id))
                opponent_name = opponent.display_name
            except:
                pass
            
            is_winner = game['winner_id'] == self.target_id
            result_symbol = "✅ Vitória" if is_winner else ("🤝 Empate" if game['result'] == 'draw' else "❌ Derrota")
            
            rating_change = ""
            if game['player1_id'] == self.target_id:
                if game['player1_rating_after']:
                    change = game['player1_rating_after'] - game['player1_rating_before']
                    rating_change = f" ({game['player1_rating_before']} → {game['player1_rating_after']} {'📈' if change > 0 else '📉'})"
            date_str = game['played_at'][:10] if game['played_at'] else "Data desconhecida"
            
            field_value = f"{result_symbol} vs **{opponent_name}**\n**Modo:** {get_mode_emoji(game['mode'])} {game['mode'].upper()}\n**Data:** {date_str}{rating_change}"
            if game.get('game_url'):
                field_value += f"\n**[Ver partida]({game['game_url']})**"
            
            embed.add_field(name=f"", value=field_value, inline=False)
        
        embed.set_footer(text=f"Página {self.page + 1}")
        if is_new_message:
            await interaction.response.send_message(embed=embed, view=self, ephemeral=True)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

class Statistics(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="histórico", description="Ver suas últimas partidas")
    async def historico(self, interaction: discord.Interaction, jogador: discord.User = None):
        """Mostra o histórico das últimas partidas de um jogador."""
        target_id = str(jogador.id) if jogador else str(interaction.user.id)
        
        await interaction.response.defer()
        
        games = await database.get_player_game_history(target_id, limit=50)
        
        if not games:
            embed = discord.Embed(
                title="📋 Histórico de Partidas",
                description="Nenhuma partida registrada ainda.",
                color=discord.Color.greyple()
            )
            await interaction.followup.send(embed=embed)
            return
        
        try:
            user = await self.bot.fetch_user(int(target_id))
            display_name = user.display_name
        except:
            display_name = "Jogador"
        
        view = HistoryView(self.bot, interaction.user.id, target_id, page=0)
        
        embed = discord.Embed(
            title=f"📋 Histórico de Partidas - {display_name}",
            description=f"Total de {len(games)} partidas",
            color=discord.Color.blue()
        )
        
        for game in games[:5]:
            opponent_id = game['player2_id'] if game['player1_id'] == target_id else game['player1_id']
            opponent_name = game['player2_name'] if game['player1_id'] == target_id else game['player1_name']
            
            try:
                opponent = await self.bot.fetch_user(int(opponent_id))
                opponent_name = opponent.display_name
            except:
                pass
            
            is_winner = game['winner_id'] == target_id
            result_symbol = "✅ Vitória" if is_winner else ("🤝 Empate" if game['result'] == 'draw' else "❌ Derrota")
            
            rating_change = ""
            if game['player1_id'] == target_id and game['player1_rating_after']:
                change = game['player1_rating_after'] - game['player1_rating_before']
                rating_change = f" ({game['player1_rating_before']} → {game['player1_rating_after']} {'📈' if change > 0 else '📉'})"
            elif game['player2_id'] == target_id and game['player2_rating_after']:
                change = game['player2_rating_after'] - game['player2_rating_before']
                rating_change = f" ({game['player2_rating_before']} → {game['player2_rating_after']} {'📈' if change > 0 else '📉'})"
            
            date_str = game['played_at'][:10] if game['played_at'] else "Data desconhecida"
            
            field_value = f"{result_symbol} vs **{opponent_name}**\n**Modo:** {get_mode_emoji(game['mode'])} {game['mode'].upper()}\n**Data:** {date_str}{rating_change}"
            if game.get('game_url'):
                field_value += f"\n**[Ver partida]({game['game_url']})**"
            
            embed.add_field(name=f"", value=field_value, inline=False)
        
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="badges", description="Ver seus achievements desbloqueados")
    async def badges(self, interaction: discord.Interaction, jogador: discord.User = None):
        """Mostra os achievements de um jogador."""
        target_id = str(jogador.id) if jogador else str(interaction.user.id)
        
        await interaction.response.defer()
        
        achievements = await database.get_player_achievements(target_id)
        
        try:
            user = await self.bot.fetch_user(int(target_id))
            display_name = user.display_name
        except:
            display_name = "Jogador"
        
        embed = discord.Embed(
            title=f"🎖️ ➜ Achievements - {display_name}",
            description=f"Total de {len(achievements)} desbloqueados",
            color=discord.Color.gold()
        )
        
        if not achievements:
            embed.description = "Nenhum achievement desbloqueado ainda. Comece a jogar!"
        else:
            for ach in achievements:
                config = ACHIEVEMENTS_CONFIG.get(ach['achievement_type'], {})
                name = config.get('name', ach['achievement_name'])
                desc = config.get('description', ach['description'] or 'Sem descrição')
                date = ach['unlocked_at'][:10] if ach['unlocked_at'] else "Data desconhecida"
                
                embed.add_field(
                    name=name,
                    value=f"{desc}\n_Desbloqueado em {date}_",
                    inline=False
                )
        
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Statistics(bot))
