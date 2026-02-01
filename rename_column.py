import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

# Check current columns in swiss_participants
cursor.execute("PRAGMA table_info(swiss_participants)")
columns = cursor.fetchall()
print("Current swiss_participants columns:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

# If discord_id exists and player_id doesn't, rename it
if any(col[1] == 'discord_id' for col in columns) and not any(col[1] == 'player_id' for col in columns):
    try:
        cursor.execute("ALTER TABLE swiss_participants RENAME COLUMN discord_id TO player_id")
        print("Renamed discord_id to player_id in swiss_participants")
    except Exception as e:
        print(f"Failed to rename column: {e}")
else:
    print("Column already correct or not found")

conn.commit()
conn.close()