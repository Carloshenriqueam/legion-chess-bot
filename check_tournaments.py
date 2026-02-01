import asyncio
import database

async def check_tournaments():
    # Get all tournaments
    conn = database.get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, status, numero_de_rodadas FROM tournaments")
    tournaments = cursor.fetchall()
    conn.close()

    print("All tournaments:")
    for t in tournaments:
        print(f"ID: {t['id']}, Name: {t['name']}, Status: {t['status']}, Numero de Rodadas: {t['numero_de_rodadas']}")

    # Check tournament 56 specifically
    tournament = await database.get_tournament(56)
    if tournament:
        print(f"\nTournament 56 details: {tournament}")

        # Get participants
        participants = await database.get_tournament_participants(56)
        print(f"Participants: {len(participants)}")
        for p in participants:
            print(f"  {p['discord_username']}: {p['points']} points")

        # Get matches
        matches = await database.get_tournament_matches(56)
        print(f"Matches: {len(matches)}")
        for m in matches:
            print(f"  Round {m['round_number']}, Match {m['match_number']}: {m['player1_name']} vs {m.get('player2_name', 'BYE')} - Status: {m['status']}, Winner: {m.get('winner_id')}")

if __name__ == "__main__":
    asyncio.run(check_tournaments())
