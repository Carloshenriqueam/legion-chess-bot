"""
Script para atualizar os avatares dos jogadores existentes
Este script busca o avatar_hash de cada jogador via Discord API
"""
import sqlite3
import sys
import os
from pathlib import Path

# Importar módulos do bot
BOT_PATH = r"C:\Users\carlu\legion-chess-bot"
sys.path.insert(0, BOT_PATH)

try:
    import discord
    from dotenv import load_dotenv
    
    load_dotenv()
    
    DB_PATH = os.path.join(BOT_PATH, 'legion_chess.db')
    
    async def update_avatars():
        """Busca e atualiza avatares dos jogadores"""
        
        # Conectar ao banco
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Buscar todos os jogadores
        cursor.execute('SELECT discord_id, discord_username FROM players')
        players = cursor.fetchall()
        
        # Criar cliente Discord para buscar informações
        intents = discord.Intents.default()
        bot = discord.Bot(intents=intents)
        
        token = os.environ.get('DISCORD_TOKEN')
        
        @bot.event
        async def on_ready():
            print(f'Bot conectado como {bot.user}')
            
            # Atualizar avatar de cada jogador
            for discord_id, username in players:
                try:
                    user = await bot.fetch_user(int(discord_id))
                    avatar_hash = user.avatar.key if user.avatar else None
                    
                    if avatar_hash:
                        cursor.execute(
                            'UPDATE players SET avatar_hash = ? WHERE discord_id = ?',
                            (avatar_hash, discord_id)
                        )
                        conn.commit()
                        print(f'[OK] Avatar atualizado para {username}')
                    else:
                        print(f'[INFO] {username} não tem avatar customizado')
                        
                except Exception as e:
                    print(f'[ERRO] Falha ao buscar avatar de {username}: {e}')
            
            conn.close()
            await bot.close()
        
        await bot.start(token)
    
    # Executar
    import asyncio
    asyncio.run(update_avatars())
    
except Exception as e:
    print(f'Erro ao atualizar avatares: {e}')
    import traceback
    traceback.print_exc()
