import asyncio
import sys
import os

# Adiciona o diretório atual ao path para importar database
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database

async def test_draw_tournament():
    print("🧪 Testando torneio com empates...")

    # Inicializar banco
    await database.init_database()
    print("✅ Banco inicializado")

    # Criar jogadores
    player_ids = []
    for i in range(1, 5):
        discord_id = f"{i:03d}000000"
        username = f"Player{i}"
        await database.register_player(discord_id, username)
        player_ids.append(discord_id)
    print("✅ 4 jogadores criados")

    # Criar torneio
    tournament_id = await database.create_tournament(
        name="Torneio com Empates",
        description="Teste de empates",
        mode="blitz",
        time_control="5+3",
        max_participants=4,
        min_participants=4,
        created_by="000000000",
        numero_de_rodadas=3
    )
    print(f"✅ Torneio criado com ID: {tournament_id}")

    # Inscrever jogadores
    for player_id in player_ids:
        success, message = await database.join_tournament(tournament_id, player_id)
        if not success:
            print(f"❌ Erro ao inscrever {player_id}: {message}")
            return
    print("✅ Todos os 4 jogadores inscritos")

    # Iniciar torneio
    success, message = await database.start_tournament(tournament_id)
    if not success:
        print(f"❌ Erro ao iniciar torneio: {message}")
        return
    print(f"✅ Torneio iniciado: {message}")

    # Simular todas as partidas da primeira rodada
    matches = await database.get_tournament_matches(tournament_id, round_num=1)
    print(f"📊 Partidas da rodada 1: {len(matches)}")

    # Simular vitória na primeira partida
    if matches:
        match = matches[0]
        challenge_id = match['challenge_id']
        winner_id = match['player1_id']
        loser_id = match['player2_id']
        await database.mark_challenge_as_finished(challenge_id, winner_id, loser_id, 'win', 'pgn_test')
        print(f"✅ Partida 1: {match['player1_name']} venceu {match['player2_name']}")

    # Simular empate na segunda partida
    if len(matches) > 1:
        match = matches[1]
        challenge_id = match['challenge_id']
        player1_id = match['player1_id']
        player2_id = match['player2_id']
        await database.mark_challenge_as_finished(challenge_id, None, None, 'draw', 'pgn_draw_test')
        print(f"✅ Partida 2: {match['player1_name']} empatou com {match['player2_name']}")

    # Verificar standings após primeira rodada
    standings = await database.get_tournament_standings(tournament_id)
    print("📊 Classificação após rodada 1:")
    for i, player in enumerate(standings, 1):
        print(f"  {i}. {player['discord_username']}: {player['points']} pontos")

    # Avançar para próxima rodada
    success, message = await database.advance_tournament_round(tournament_id)
    if success:
        print(f"✅ {message}")
    else:
        print(f"❌ Erro ao avançar: {message}")

    # Verificar partidas da segunda rodada
    matches_round2 = await database.get_tournament_matches(tournament_id, round_num=2)
    print(f"📊 Partidas da rodada 2: {len(matches_round2)}")
    for match in matches_round2:
        p1_name = match.get('player1_name', 'Unknown')
        p2_name = match.get('player2_name', 'BYE')
        print(f"  - {p1_name} vs {p2_name} ({match['status']})")

    # Simular uma partida da segunda rodada (empate)
    if matches_round2:
        match = matches_round2[0]
        challenge_id = match['challenge_id']
        player1_id = match['player1_id']
        player2_id = match['player2_id']
        await database.mark_challenge_as_finished(challenge_id, None, None, 'draw', 'pgn_draw_round2')
        print(f"✅ Partida da rodada 2: {match['player1_name']} empatou com {match['player2_name']}")

    # Verificar standings após segunda rodada
    standings = await database.get_tournament_standings(tournament_id)
    print("📊 Classificação após rodada 2:")
    for i, player in enumerate(standings, 1):
        print(f"  {i}. {player['discord_username']}: {player['points']} pontos")

    print("🧪 Teste de torneio com empates concluído!")

if __name__ == "__main__":
    asyncio.run(test_draw_tournament())
