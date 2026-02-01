import asyncio
import database

async def test_monitor():
    # Simular o que o monitor faz
    challenges = await database.get_finished_games_to_process()
    print(f'Desafios encontrados: {len(challenges)}')

    if challenges:
        for ch in challenges:
            print(f'ID: {ch["id"]}, URL: {ch["game_url"]}')

if __name__ == '__main__':
    asyncio.run(test_monitor())
