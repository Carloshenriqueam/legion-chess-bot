import sqlite3

DB_PATH = 'legion_chess.db'

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Verificar se a coluna já existe
cursor.execute("PRAGMA table_info(players)")
columns = [col[1] for col in cursor.fetchall()]

if 'avatar_hash' not in columns:
    print("Adicionando coluna avatar_hash...")
    cursor.execute("ALTER TABLE players ADD COLUMN avatar_hash TEXT")
    conn.commit()
    print("Coluna adicionada com sucesso!")
else:
    print("Coluna avatar_hash já existe.")

conn.close()
