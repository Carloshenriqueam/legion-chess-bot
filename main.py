# main.py
import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv
import sys
import logging
import lichess_api
import database
import subprocess
import time
import atexit
# Carrega as variÃ¡veis do arquivo .env
load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger(__name__)

# Importa nossos mÃ³dulos
import database

# --- INICIALIZAÃ‡ÃƒO DO BOT ---

# Usamos a classe Bot, mas poderÃ­amos usar Client para mais controle
intents = discord.Intents.default()
intents.message_content = True # Ainda Ã© Ãºtil para algumas interaÃ§Ãµes
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents) # O prefix ainda pode ser Ãºtil para comandos de admin

# --- CONFIGURAÃ‡ÃƒO DE SERVIDORES PERMITIDOS ---
ALLOWED_GUILDS = None

def load_allowed_guilds():
    """Carrega a lista de servidores permitidos das variÃ¡veis de ambiente."""
    global ALLOWED_GUILDS
    allowed_guilds_str = os.environ.get('ALLOWED_GUILDS')
    if allowed_guilds_str:
        ALLOWED_GUILDS = [int(gid.strip()) for gid in allowed_guilds_str.split(',') if gid.strip()]
    else:
        # Fallback para GUILD_ID Ãºnico
        guild_id = os.environ.get('GUILD_ID')
        if guild_id:
            ALLOWED_GUILDS = [int(guild_id)]
        else:
            ALLOWED_GUILDS = None  # Servidores globais

def is_guild_allowed(guild_id: int) -> bool:
    """Verifica se um servidor estÃ¡ na lista de permitidos."""
    if ALLOWED_GUILDS is None:
        return True  # Se nÃ£o hÃ¡ restriÃ§Ã£o, permite todos
    return guild_id in ALLOWED_GUILDS

async def guild_check(interaction: discord.Interaction) -> bool:
    """Check para comandos: verifica se o servidor Ã© permitido."""
    if ALLOWED_GUILDS is None:
        return True  # Sem restriÃ§Ã£o
    
    if interaction.guild and interaction.guild.id in ALLOWED_GUILDS:
        return True
    
    # Servidor nÃ£o permitido
    await interaction.response.send_message(
        "❌ **Servidor nÃ£o autorizado**\n\n"
        "Este bot estÃ¡ configurado para funcionar apenas em servidores especÃ­ficos.",
        ephemeral=True
    )
    return False

@bot.event
async def on_ready():
    if bot.user:
        print(f'âœ… {bot.user} estÃ¡ online!')

    # Carrega configuraÃ§Ã£o de servidores permitidos
    load_allowed_guilds()
    if ALLOWED_GUILDS:
        print(f"🔒 Bot restrito a {len(ALLOWED_GUILDS)} servidor(es): {ALLOWED_GUILDS}")
    else:
        print("🌐 Bot funcionando globalmente (sem restriÃ§Ã£o de servidores)")

    # Carrega os cogs ANTES da sincronizaÃ§Ã£o
    try:
        await load_cogs()
        print("âœ… Cogs carregados com sucesso.")
    except Exception as e:
        print(f"âŒ Erro ao carregar cogs: {e}")
        import traceback
        traceback.print_exc()
        return

    await database.init_database()

    # Sincroniza comandos slash APÃ“S carregar os cogs
    try:
        # Verifica se há ALLOWED_GUILDS definido (suporta múltiplos servidores separados por vírgula)
        allowed_guilds_str = os.environ.get('ALLOWED_GUILDS')
        if allowed_guilds_str:
            # Parse dos IDs dos servidores permitidos
            allowed_guild_ids = [int(gid.strip()) for gid in allowed_guilds_str.split(',') if gid.strip()]
            total_synced = 0
            for guild_id in allowed_guild_ids:
                guild = bot.get_guild(guild_id)
                if guild:
                    synced = await bot.tree.sync(guild=guild)
                    print(f"✅ {len(synced)} slash commands sincronizados para o servidor (ID: {guild_id}).")
                    total_synced += len(synced)
                else:
                    print(f"❌ Servidor com ID {guild_id} não encontrado.")
            print(f"✅ Total de {total_synced} slash commands sincronizados para {len(allowed_guild_ids)} servidores.")
        else:
            # Fallback para GUILD_ID único (compatibilidade)
            guild_id = os.environ.get('GUILD_ID')
            if guild_id:
                # Se há GUILD_ID definido, sincroniza apenas para esse servidor
                guild = bot.get_guild(int(guild_id))
                if guild:
                    synced = await bot.tree.sync(guild=guild)
                    print(f"✅ {len(synced)} slash commands sincronizados para o servidor específico (ID: {guild_id}).")
                else:
                    print(f"❌ Servidor com ID {guild_id} não encontrado.")
            else:
                # Sincronização global
                synced = await bot.tree.sync()
                print(f"✅ {len(synced)} slash commands sincronizados globalmente.")
    except Exception as e:
        print(f"❌ Erro ao sincronizar slash commands: {e}")
        import traceback
        traceback.print_exc()

    # Inicia a tarefa de verificação de partidas em segundo plano
    import tasks
    tasks.set_bot_instance(bot)
    asyncio.create_task(tasks.start_background_tasks())

@bot.event
async def on_interaction(interaction: discord.Interaction):
    """Intercepta interações de comandos slash para verificar permissões de servidor."""
    # Permitir interações de componentes (botões, selects) - essas são respostas válidas
    if interaction.type == discord.InteractionType.component:
        return

    # Só verifica interações de comandos slash
    if interaction.type == discord.InteractionType.application_command:
        if ALLOWED_GUILDS is not None:  # Se há restrição de servidores
            if not interaction.guild or interaction.guild.id not in ALLOWED_GUILDS:
                try:
                    # Verificar se a interação já foi respondida
                    if not interaction.response.is_done():
                        await interaction.response.send_message(
                            "❌ **Servidor não autorizado**\n\n"
                            "Este bot está configurado para funcionar apenas em servidores específicos.",
                            ephemeral=True
                        )
                    else:
                        # Se já foi respondida, tentar followup
                        await interaction.followup.send(
                            "❌ **Servidor não autorizado**\n\n"
                            "Este bot está configurado para funcionar apenas em servidores específicos.",
                            ephemeral=True
                        )
                except (discord.errors.InteractionResponded, discord.errors.HTTPException) as e:
                    # Interação já foi respondida ou outro erro, ignorar
                    logger.warning(f"Não foi possível enviar mensagem de erro para interação não autorizada: {e}")
                return  # Bloqueia a execução do comando

@bot.event
async def on_close():
    """Evento chamado quando o bot está sendo fechado."""
    print("🛑 Bot sendo fechado... Cancelando tarefas em segundo plano.")
    
    # Parar tarefas específicas do bot adequadamente
    try:
        import tasks
        await tasks.stop_background_tasks()
        print("✅ Tarefas em segundo plano paradas com sucesso")
    except Exception as e:
        print(f"⚠️ Erro ao parar tarefas em segundo plano: {e}")
    
    # Fecha sessões HTTP pendentes
    import lichess_api
    try:
        await lichess_api.cleanup_sessions()
        print("✅ Sessões HTTP fechadas com sucesso")
    except Exception as e:
        print(f"⚠️ Erro ao fechar sessões HTTP: {e}")
    
    print("✅ Bot fechado com sucesso.")

async def load_cogs():
    """Carrega todos os cogs da pasta 'cogs'."""
    await bot.load_extension("cogs.utility")
    await bot.load_extension("cogs.chess")
    await bot.load_extension("cogs.rankings")
    await bot.load_extension("cogs.tournaments")
    await bot.load_extension("cogs.official_tournament")
    await bot.load_extension("cogs.statistics")

# --- GERENCIAMENTO DO BACKEND ---
backend_proc = None

def start_backend():
    """Inicia o servidor Flask do backend em subprocess."""
    global backend_proc
    
    # Caminhos do backend
    venv_python = r"C:\Users\carlu\legion-chess-bot\venv\Scripts\python.exe"
    backend_app = r"C:\Users\carlu\Desktop\legionchess-new\backend\app.py"
    
    try:
        # Abre arquivos de log
        stdout_log = open('backend_stdout.log', 'a', encoding='utf-8')
        stderr_log = open('backend_stderr.log', 'a', encoding='utf-8')
        
        # Inicia o subprocess
        backend_proc = subprocess.Popen(
            [venv_python, backend_app],
            stdout=stdout_log,
            stderr=stderr_log,
            env=os.environ.copy()
        )
        print(f"âœ… Backend Flask iniciado (PID: {backend_proc.pid})")
        time.sleep(2)  # Aguarda Flask inicializar
    except Exception as e:
        print(f"âŒ Erro ao iniciar backend: {e}")

def stop_backend():
    """Para o servidor Flask do backend."""
    global backend_proc
    
    if backend_proc is not None:
        try:
            if backend_proc.poll() is None:  # Verifica se ainda estÃ¡ rodando
                backend_proc.terminate()
                backend_proc.wait(timeout=5)
                print("âœ… Backend Flask parado")
        except Exception as e:
            print(f"âš ï¸ Erro ao parar backend: {e}")
            try:
                backend_proc.kill()
            except:
                pass

# Registra stop_backend para executar ao sair
atexit.register(stop_backend)

if __name__ == '__main__':
    discord_token = os.environ.get('DISCORD_TOKEN')
    if not discord_token:
        print('âŒ DISCORD_TOKEN nÃ£o encontrado no arquivo .env!')
        exit(1)

    # Inicia o backend antes do bot
    start_backend()
    
    bot.run(discord_token)

