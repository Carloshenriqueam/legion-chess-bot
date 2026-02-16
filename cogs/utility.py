# cogs/utility.py
import discord
from discord import app_commands
from discord.ext import commands

class Utility(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ajuda", description="Mostra todos os comandos disponíveis.")
    async def ajuda(self, interaction: discord.Interaction):
        """Mostra todos os comandos disponíveis."""
        embed = discord.Embed(
            title="♦ Legion Chess App - Comandos",
            description="Sistema de xadrez competitivo — comandos /slash disponíveis",
            color = 0xCD0000
        )
        
        embed.add_field(
            name="📝 Registro",
            value=("`/registrar [lichess_username]` - Registra seu username Lichess\n"
                   "`/verificar-lichess` - Verifica sua conta Lichess\n"
                   "`/atualizar-nome [novo_nome]` - Atualiza seu nome no banco\n"
                   "`/perfil [@jogador]` - Mostra o perfil de um jogador"),
            inline=False
        )
        
        embed.add_field(
            name="⚔️ Desafios",
            value=("`/desafiar @jogador [modo] [time_control] [valer_rating]` - Desafia outro jogador\n"
                   "`/aceitar <id>` - Aceita um desafio\n"
                   "`/recusar <id>` - Recusa um desafio\n"
                   "`/agendar-partida @jog1 @jog2 [tempo] [rating] [DD/MM/YYYY HH:MM]` - Agenda partida (ADMIN)\n"
                   "`/partidas-programadas` - Lista suas partidas agendadas\n"
                   "`/desafios` - Lista seus desafios pendentes"),
            inline=False
        )

        embed.add_field(
            name="🏆 Torneios (Suíço)",
            value=("`/criar_swiss` - Cria torneio suíço local\n"
                   "`/entrar_swiss <id>` - Mensagem com botão para entrar\n"
                   "`/iniciar_torneio <id>` - Inicia torneio (suíço/regular)\n"
                   "`/abandonar_torneio <id>` - Abandona torneio (penalidade)"),
            inline=False
        )

        embed.add_field(
            name="🏆 Torneios Oficiais (Bracket)",
            value=("`/torneio_oficial criar` - Cria torneio oficial (bracket)\n"
                   "`/torneio_oficial iniciar <id>` - Inicia o torneio\n"
                   "`/torneio_oficial bracket <id>` - Exibe o bracket\n"
                   "`/torneio_oficial partidas_pendentes <id>` - Lista partidas pendentes"),
            inline=False
        )

        embed.add_field(
            name="📊 Rankings & Estatísticas",
            value=("`/rankings` - Mostra os rankings\n"
                   "`/set_fixed_ranking #canal` - Define ranking fixo (admin)\n"
                   "`/set_ranking_channel` / ` /remove_ranking_channel` / `recreate_fixed_ranking` - Admin\n"
                   "`/histórico` - Suas últimas partidas\n"
                   "`/badges` - Seus achievements"),
            inline=False
        )

        embed.add_field(
            name="🧩 Puzzles",
            value=("`/puzzle-diario` - Puzzle do dia (admin)\n"
                   "`/responder <movimento>` - Responder puzzle"),
            inline=False
        )

        embed.add_field(
            name="🔧 Utilitários / Admin",
            value=("`/ping` - Latência do bot\n"
                   "`/ajuda` - Mostra esta mensagem\n"
                   "`/sync_commands` - Sincroniza comandos (admin)\n"
                   "`/check_games` / `debug-scheduled` / `ativar-atrasados` - Debug / admin"),
            inline=False
        )
    
        
        # Em vez de ctx.reply, usamos interaction.response.send_message
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="ping", description="Testa se o bot está respondendo.")
    async def ping(self, interaction: discord.Interaction):
        """Testa se o bot está respondendo."""
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f'🏓 Pong! Latência: {latency}ms')

    @app_commands.command(name="sync_commands", description="Sincroniza os comandos do bot com o Discord (apenas administradores).")
    @app_commands.checks.has_permissions(administrator=True)
    async def sync_commands(self, interaction: discord.Interaction):
        """Sincroniza os comandos do bot com o Discord."""
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.tree.sync()
            await interaction.followup.send("✅ Comandos sincronizados com sucesso! Os comandos slash agora devem aparecer no Discord.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao sincronizar comandos: {str(e)}", ephemeral=True)

    @sync_commands.error
    async def sync_commands_error(self, interaction: discord.Interaction, error):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("❌ Você precisa ser administrador para usar este comando.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ocorreu um erro ao sincronizar os comandos.", ephemeral=True)

    @commands.command(name="sync_commands")
    @commands.has_permissions(administrator=True)
    async def sync_commands_prefix(self, ctx):
        """Sincroniza os comandos do bot com o Discord (comando de prefixo)."""
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(f"✅ {len(synced)} comandos sincronizados com sucesso! Os comandos slash agora devem aparecer no Discord.")
        except Exception as e:
            await ctx.send(f"❌ Erro ao sincronizar comandos: {str(e)}")

    @sync_commands_prefix.error
    async def sync_commands_prefix_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Você precisa ser administrador para usar este comando.")
        else:
            await ctx.send("❌ Ocorreu um erro ao sincronizar os comandos.")

# Função necessária para carregar o Cog
async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
    print("[LOG] Utility cog carregado com 3 comandos.")
