import asyncio
import database

async def debug_standings():
    tournament_id = 9

    # Get tournament matches
    matches = await database.get_tournament_matches(tournament_id)
    print(f"Matches for tournament {tournament_id}:")
    for match in matches:
        print(f"  Round {match['round_number']}, Match {match['match_number']}: {match['player1_name']} vs {match.get('player2_name', 'BYE')} - Status: {match['status']}, Winner: {match.get('winner_id', 'None')}")

    # Update standings
    await database.update_tournament_standings(tournament_id)

    # Get standings after update
    standings = await database.get_tournament_standings(tournament_id)
    print('\nStandings after update:')
    for i, p in enumerate(standings):
        print(f'{i+1}. {p["discord_username"]}: {p["points"]} pontos')

if __name__ == "__main__":
    asyncio.run(debug_standings())
