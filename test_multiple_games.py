import asyncio
import lichess_api

async def test_multiple_games():
    urls = [
        'https://lichess.org/B5xi4H5C',
        'https://lichess.org/QxuiY3ww',
        'https://lichess.org/en64tBib'
    ]

    for url in urls:
        outcome = await lichess_api.get_game_outcome(url)
        print(f'URL: {url}')
        print(f'  Finished: {outcome["finished"]}')
        print(f'  Is draw: {outcome["is_draw"]}')
        print(f'  Winner color: {outcome["winner_color"]}')
        print(f'  Reason: {outcome["reason"]}')
        print()

if __name__ == '__main__':
    asyncio.run(test_multiple_games())
