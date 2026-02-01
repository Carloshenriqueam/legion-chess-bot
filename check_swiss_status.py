import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

cursor.execute("SELECT id, name, status FROM swiss_tournaments ORDER BY id DESC LIMIT 5")
tournaments = cursor.fetchall()

print("Recent Swiss tournaments:")
for t in tournaments:
    print(f"ID: {t[0]}, Name: {t[1]}, Status: {t[2]}")

conn.close()