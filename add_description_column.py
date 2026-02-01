import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

# Check if description column exists
cursor.execute("PRAGMA table_info(swiss_tournaments)")
columns = [col[1] for col in cursor.fetchall()]

if 'description' not in columns:
    try:
        cursor.execute("ALTER TABLE swiss_tournaments ADD COLUMN description TEXT")
        print("Added description column to swiss_tournaments")
    except Exception as e:
        print(f"Failed to add description column: {e}")
else:
    print("Description column already exists")

conn.commit()
conn.close()