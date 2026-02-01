import asyncio
import database

async def test_get_finished_games():
    challenges = await database.get_finished_games_to_process()
    print(f'get_finished_games_to_process retornou: {len(challenges)} desafios')

    # Verificar o que a query retorna
    if challenges:
        for ch in challenges:
            print(f'  ID: {ch["id"]}, Status: {ch["status"]}, URL: {ch["game_url"]}')

if __name__ == '__main__':
    asyncio.run(test_get_finished_games())
