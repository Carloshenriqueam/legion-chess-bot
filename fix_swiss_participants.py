import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

# Check current columns in swiss_participants
cursor.execute("PRAGMA table_info(swiss_participants)")
columns = cursor.fetchall()
print("Current swiss_participants columns:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

col_names = [col[1] for col in columns]

# Rename discord_id to player_id if exists
if 'discord_id' in col_names and 'player_id' not in col_names:
    try:
        cursor.execute("ALTER TABLE swiss_participants RENAME COLUMN discord_id TO player_id")
        print("Renamed discord_id to player_id")
    except Exception as e:
        print(f"Failed to rename discord_id to player_id: {e}")

# Rename score to points if exists
if 'score' in col_names and 'points' not in col_names:
    try:
        cursor.execute("ALTER TABLE swiss_participants RENAME COLUMN score TO points")
        print("Renamed score to points")
    except Exception as e:
        print(f"Failed to rename score to points: {e}")

# Add tiebreak_score if missing
if 'tiebreak_score' not in col_names:
    try:
        cursor.execute("ALTER TABLE swiss_participants ADD COLUMN tiebreak_score REAL DEFAULT 0.0")
        print("Added tiebreak_score column")
    except Exception as e:
        print(f"Failed to add tiebreak_score: {e}")

conn.commit()
conn.close()