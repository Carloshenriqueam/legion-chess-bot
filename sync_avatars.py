"""
Comando para atualizar avatares dos jogadores no banco de dados
Execute este arquivo para atualizar os avatares de todos os jogadores
"""
import sqlite3
import os
import sys
from pathlib import Path

BOT_PATH = r"C:\Users\carlu\legion-chess-bot"
sys.path.insert(0, BOT_PATH)

DB_PATH = os.path.join(BOT_PATH, 'legion_chess.db')

def update_avatars_sync():
    """Atualiza os avatares localmente via discord.py"""
    try:
        import discord
        from dotenv import load_dotenv
        import asyncio
        
        load_dotenv()
        
        async def fetch_and_update():
            intents = discord.Intents.default()
            client = discord.Client(intents=intents)
            
            token = os.environ.get('DISCORD_TOKEN')
            
            @client.event
            async def on_ready():
                print(f'[CONECTADO] {client.user}')
                
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                
                # Buscar todos os jogadores
                cursor.execute('SELECT discord_id, discord_username FROM players')
                players = cursor.fetchall()
                
                updated = 0
                failed = 0
                
                for discord_id_str, username in players:
                    try:
                        discord_id = int(discord_id_str)
                        user = await client.fetch_user(discord_id)
                        
                        # Obter avatar hash
                        avatar_hash = user.avatar.key if user.avatar else None
                        
                        # Atualizar no banco
                        cursor.execute(
                            'UPDATE players SET avatar_hash = ? WHERE discord_id = ?',
                            (avatar_hash, discord_id_str)
                        )
                        conn.commit()
                        
                        status = 'CUSTOMIZADO' if avatar_hash else 'PADRAO'
                        print(f'[OK] {username} - Avatar {status}')
                        updated += 1
                        
                    except Exception as e:
                        print(f'[ERRO] {username}: {e}')
                        failed += 1
                
                conn.close()
                
                print(f'\n[RESUMO] {updated} atualizados, {failed} erros')
                await client.close()
            
            await client.start(token)
        
        asyncio.run(fetch_and_update())
        
    except ImportError:
        print('[ERRO] discord.py nao esta instalado')
    except Exception as e:
        print(f'[ERRO] Falha ao atualizar avatares: {e}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print('[INFO] Iniciando atualizacao de avatares...')
    print('[AVISO] Isto pode levar alguns segundos dependendo do numero de jogadores')
    update_avatars_sync()
