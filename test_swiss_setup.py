import asyncio
import database

async def test():
    await database.init_database()
    print('[OK] Database initialized successfully')
    
    conn = database.get_conn()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print('\nTables in database:')
    for table in tables:
        print(f'  - {table[0]}')
    
    swiss_tables = [t[0] for t in tables if 'swiss' in t[0].lower()]
    if swiss_tables:
        print('\n[SUCCESS] Swiss tables created!')
        for t in swiss_tables:
            print(f'   * {t}')
    else:
        print('\n[ERROR] Swiss tables not created')
    
    conn.close()

if __name__ == '__main__':
    asyncio.run(test())
