import aiohttp
import asyncio

async def test_swiss_api():
    async with aiohttp.ClientSession() as session:
        async with session.post(
            'https://lichess.org/api/swiss',
            headers={
                'Authorization': 'Bearer YOUR_TOKEN',
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            data='name=Test&clockTime=10&clockIncrement=0&nbRounds=5&rated=true&variant=standard'
        ) as response:
            print(f"Status: {response.status}")
            text = await response.text()
            print(f"Response: {text}")

asyncio.run(test_swiss_api())
