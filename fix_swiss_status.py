import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

# Update status from 'waiting' to 'open'
cursor.execute("UPDATE swiss_tournaments SET status = 'open' WHERE status = 'waiting'")
updated = cursor.rowcount
print(f"Updated {updated} tournaments from 'waiting' to 'open'")

conn.commit()
conn.close()