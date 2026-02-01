import sqlite3

conn = sqlite3.connect('legion_chess.db')
cursor = conn.cursor()

# Check current columns
cursor.execute("PRAGMA table_info(swiss_tournaments)")
columns = [col[1] for col in cursor.fetchall()]

print("Current columns:", columns)

missing_columns = [
    ('time_control', 'TEXT NOT NULL'),
    ('nb_rounds', 'INTEGER NOT NULL'),
    ('created_by', 'TEXT NOT NULL'),
    ('rated', 'INTEGER DEFAULT 1'),
    ('min_rating', 'INTEGER'),
    ('max_rating', 'INTEGER')
]

for col_name, col_type in missing_columns:
    if col_name not in columns:
        try:
            cursor.execute(f"ALTER TABLE swiss_tournaments ADD COLUMN {col_name} {col_type}")
            print(f"Added {col_name} column")
        except Exception as e:
            print(f"Failed to add {col_name}: {e}")
    else:
        print(f"{col_name} already exists")

conn.commit()
conn.close()