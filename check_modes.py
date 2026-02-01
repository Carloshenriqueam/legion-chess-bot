import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

modes = ['bullet', 'blitz', 'rapid', 'classic']

cursor.execute('SELECT discord_username, discord_id FROM players')
players = cursor.fetchall()

print("Dados de cada jogador por modo:\n")

for username, discord_id in players:
    print(f"\n{username} ({discord_id}):")
    for mode in modes:
        cursor.execute(f'''
            SELECT rating_{mode}, wins_{mode}, losses_{mode}, draws_{mode}
            FROM players
            WHERE discord_username = ?
        ''', (username,))
        row = cursor.fetchone()
        if row:
            rating, wins, losses, draws = row
            total = (wins or 0) + (losses or 0) + (draws or 0)
            print(f"  {mode:8} -> Rating: {rating}, Total: {total} ({wins or 0}W-{losses or 0}L-{draws or 0}D)")

conn.close()
