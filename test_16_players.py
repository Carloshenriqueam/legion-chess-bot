import asyncio
import sys
import os

# Adiciona o diretório atual ao path para importar database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database

async def test_16_players_tournament():
    print("🧪 Testando torneio com 16 jogadores...")

    # Inicializar banco
    await database.init_database()
    print("✅ Banco inicializado")

    # Criar jogadores
    player_ids = []
    for i in range(1, 17):
        discord_id = f"{i:03d}000000"
        username = f"Player{i}"
        await database.register_player(discord_id, username)
        player_ids.append(discord_id)
    print("✅ 16 jogadores criados")

    # Criar torneio
    tournament_id = await database.create_tournament(
        name="Torneio 16 Jogadores",
        description="Teste com 16 jogadores",
        mode="blitz",
        time_control="5+3",
        max_participants=16,
        min_participants=4,
        created_by="000000000",  # ID do criador
        numero_de_rodadas=15  # Máximo para round-robin completo
    )
    print(f"✅ Torneio criado com ID: {tournament_id}")

    # Inscrever jogadores
    for player_id in player_ids:
        success, message = await database.join_tournament(tournament_id, player_id)
        if not success:
            print(f"❌ Erro ao inscrever {player_id}: {message}")
            return
    print("✅ Todos os 16 jogadores inscritos")

    # Iniciar torneio
    success, message = await database.start_tournament(tournament_id)
    if not success:
        print(f"❌ Erro ao iniciar torneio: {message}")
        return
    print(f"✅ Torneio iniciado: {message}")

    # Verificar partidas criadas
    matches = await database.get_tournament_matches(tournament_id)
    print(f"📊 Partidas criadas: {len(matches)}")
    for match in matches[:10]:  # Mostra primeiras 10
        p1_name = match.get('player1_name', 'Unknown')
        p2_name = match.get('player2_name', 'BYE')
        print(f"  - Rodada {match['round_number']}, Partida {match['match_number']}: {p1_name} vs {p2_name} ({match['status']})")
    if len(matches) > 10:
        print(f"  ... e mais {len(matches) - 10} partidas")

    # Verificar participantes
    participants = await database.get_tournament_participants(tournament_id)
    print(f"📊 Participantes: {len(participants)}")

    print("🧪 Teste de torneio com 16 jogadores concluído!")

if __name__ == "__main__":
    asyncio.run(test_16_players_tournament())
