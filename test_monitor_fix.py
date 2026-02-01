import asyncio
import database
import lichess_api
import tasks

async def test_monitor():
    # Inicializa banco
    await database.init_database()

    # Configura monitor
    tasks.set_bot_instance(None)  # Sem bot para teste

    # Simula processamento
    await tasks.check_finished_games()
    print('Teste concluído')

if __name__ == "__main__":
    asyncio.run(test_monitor())
