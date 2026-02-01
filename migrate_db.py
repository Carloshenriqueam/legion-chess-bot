import asyncio
import database

async def main():
    await database.init_database()
    print("Database initialized.")

if __name__ == "__main__":
    asyncio.run(main())