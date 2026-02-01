import sqlite3

conn = sqlite3.connect('legion_chess.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Ver último torneio
c.execute("SELECT id, name, status, nb_rounds FROM swiss_tournaments ORDER BY id DESC LIMIT 1")
t = c.fetchone()

if t:
    print(f"Torneio: {t['id']} - {t['name']}")
    print(f"Status: {t['status']}, Rodadas: {t['nb_rounds']}")
    print()
    
    # Ver pairings por rodada
    c.execute("""
        SELECT round_number, COUNT(*) total,
               SUM(CASE WHEN status='finished' THEN 1 ELSE 0 END) finished,
               SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) pending
        FROM swiss_pairings
        WHERE tournament_id = ?
        GROUP BY round_number
        ORDER BY round_number
    """, (t['id'],))
    
    print("=== Pairings por Rodada ===")
    for row in c.fetchall():
        print(f"Rodada {row['round_number']}: {row['finished']}/{row['total']} finished (pending: {row['pending']})")
    
    print()
    
    # Ver participantes
    c.execute("""
        SELECT player_id, points, wins, draws, losses
        FROM swiss_participants
        WHERE tournament_id = ?
        ORDER BY points DESC
    """, (t['id'],))
    
    print("=== Participantes ===")
    for row in c.fetchall():
        print(f"{row['player_id'][:8]}: {row['points']} pts ({row['wins']}V/{row['draws']}D/{row['losses']}L)")

conn.close()
