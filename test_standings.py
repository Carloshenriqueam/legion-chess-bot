import asyncio
import database

async def test_standings():
    # Usar o último torneio criado (ID 9)
    standings = await database.get_tournament_standings(9)
    print('Standings:')
    for i, p in enumerate(standings):
        print(f'{i+1}. {p["discord_username"]}: {p["points"]} pontos')

if __name__ == "__main__":
    asyncio.run(test_standings())
