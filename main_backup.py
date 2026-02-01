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

# Importa nossos mÃ³dulos
import database

# --- INICIALIZAÃ‡ÃƒO DO BOT ---

# Usamos a classe Bot, mas poderÃ­amos usar Client para mais controle
intents = discord.Intents.default()
intents.message_content = True # Ainda Ã© Ãºtil para algumas interaÃ§Ãµes
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents) # O prefix ainda pode ser Ãºtil para comandos de admin

@bot.event
async def on_ready():
    if bot.user:
        print(f'âœ… {bot.user} estÃ¡ online!')

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
        # Primeiro, sincroniza globalmente se nÃ£o houver GUILD_ID especÃ­fico
        guild_id = os.environ.get('GUILD_ID')
        if guild_id:
            # Se hÃ¡ GUILD_ID definido, sincroniza apenas para esse servidor
            guild = bot.get_guild(int(guild_id))
            if guild:
                synced = await bot.tree.sync(guild=guild)
                print(f"âœ… {len(synced)} slash commands sincronizados para o servidor especÃ­fico (ID: {guild_id}).")
            else:
                print(f"âŒ Servidor com ID {guild_id} nÃ£o encontrado.")
        else:
            # SincronizaÃ§Ã£o global
            synced = await bot.tree.sync()
            print(f"âœ… {len(synced)} slash commands sincronizados globalmente.")
    except Exception as e:
        print(f"âŒ Erro ao sincronizar slash commands: {e}")
        import traceback
        traceback.print_exc()

    # Inicia a tarefa de verificaÃ§Ã£o de partidas em segundo plano
    import tasks
    tasks.set_bot_instance(bot)
    asyncio.create_task(tasks.start_background_tasks())

@bot.event
async def on_close():
    """Evento chamado quando o bot está sendo fechado."""
    print("âš ï¸ Bot sendo fechado... Cancelando tarefas em segundo plano.")
    
    # Cancela todas as tarefas pendentes para evitar sessões aiohttp não fechadas
    pending_tasks = [t for t in asyncio.all_tasks() if not t.done() and t != asyncio.current_task()]
    for task in pending_tasks:
        task.cancel()
    
    # Aguarda um pouco para as tarefas serem canceladas
    await asyncio.sleep(1)
    
    # Fecha sessões HTTP pendentes
    import aiohttp
    import gc
    
    # Força coleta de lixo para liberar objetos aiohttp
    gc.collect()
    
    # Tenta fechar qualquer sessão aiohttp restante
    try:
        # Lista todos os objetos ClientSession na memória
        for obj in gc.get_objects():
            if isinstance(obj, aiohttp.ClientSession):
                if not obj.closed:
                    print(f"Fechando sessão HTTP restante: {obj}")
                    await obj.close()
    except Exception as e:
        print(f"Erro ao fechar sessões HTTP: {e}")
    
    print("âœ… Bot fechado com sucesso.")

async def load_cogs():
    """Carrega todos os cogs da pasta 'cogs'."""
    await bot.load_extension("cogs.utility")
    await bot.load_extension("cogs.chess")
    await bot.load_extension("cogs.rankings")
    await bot.load_extension("cogs.tournaments")
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

