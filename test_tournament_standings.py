import asyncio
import database

async def test_tournament_standings():
    # Create a test tournament
    tournament_id = await database.create_tournament(
        name="Test Tournament",
        description="Test",
        mode="blitz",
        time_control="5+3",
        max_participants=4,
        min_participants=2,
        created_by="test_user"
    )
    print(f"Created tournament {tournament_id}")

    # Register players
    await database.register_player("player1", "Player One")
    await database.register_player("player2", "Player Two")
    await database.register_player("player3", "Player Three")

    # Join tournament
    await database.join_tournament(tournament_id, "player1")
    await database.join_tournament(tournament_id, "player2")
    await database.join_tournament(tournament_id, "player3")

    # Start tournament
    success, message = await database.start_tournament(tournament_id)
    print(f"Start tournament: {success} - {message}")

    # Get initial standings
    standings = await database.get_tournament_standings(tournament_id)
    print("Initial standings:")
    for i, p in enumerate(standings):
        print(f'{i+1}. {p["discord_username"]}: {p["points"]} pontos')

    # Get matches
    matches = await database.get_tournament_matches(tournament_id)
    print(f"\nMatches ({len(matches)}):")
    for match in matches:
        print(f"  Round {match['round_number']}, Match {match['match_number']}: {match['player1_name']} vs {match.get('player2_name', 'BYE')} - Status: {match['status']}")

    # Simulate finishing a match
    if matches:
        match = matches[0]
        winner_id = match['player1_id']
        await database.update_tournament_match_winner(tournament_id, match['round_number'], match['match_number'], winner_id)
        print(f"\nFinished match: {match['player1_name']} won")

    # Update standings
    await database.update_tournament_standings(tournament_id)

    # Get updated standings
    standings = await database.get_tournament_standings(tournament_id)
    print("\nUpdated standings:")
    for i, p in enumerate(standings):
        print(f'{i+1}. {p["discord_username"]}: {p["points"]} pontos')

if __name__ == "__main__":
    asyncio.run(test_tournament_standings())
