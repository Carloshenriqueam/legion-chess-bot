import sqlite3

def check_unprocessed():
    conn = sqlite3.connect('legion_chess.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Verificar se há desafios com status 'accepted' mas sem registro em matches
    cursor.execute('''
        SELECT c.id, c.status, c.game_url, c.challenger_id, c.challenged_id
        FROM challenges c
        WHERE c.status = 'accepted' AND c.game_url IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
    ''')
    challenges = cursor.fetchall()
    print(f'Desafios aceitos com URL mas não processados: {len(challenges)}')
    for ch in challenges:
        print(f'  ID: {ch["id"]}, URL: {ch["game_url"]}')

    # Verificar se há desafios com status 'finished' mas sem registro em matches
    cursor.execute('''
        SELECT c.id, c.status, c.game_url, c.challenger_id, c.challenged_id
        FROM challenges c
        WHERE c.status = 'finished' AND c.game_url IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
    ''')
    finished_not_processed = cursor.fetchall()
    print(f'Desafios finalizados sem registro em matches: {len(finished_not_processed)}')
    for ch in finished_not_processed:
        print(f'  ID: {ch["id"]}, URL: {ch["game_url"]}')

    conn.close()

if __name__ == '__main__':
    check_unprocessed()
