import asyncio
import lichess_api

async def test_game():
    url = 'https://lichess.org/B5xi4H5C'
    outcome = await lichess_api.get_game_outcome(url)
    print(f'URL: {url}')
    print(f'Finished: {outcome["finished"]}')
    print(f'Is draw: {outcome["is_draw"]}')
    print(f'Winner color: {outcome["winner_color"]}')
    print(f'Reason: {outcome["reason"]}')

if __name__ == '__main__':
    asyncio.run(test_game())
