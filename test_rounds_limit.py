import asyncio
import database

async def test_tournament_rounds_limit():
    """Testa se o torneio respeita o limite de rodadas."""
    print("🧪 Testando limite de rodadas do torneio...")

    # Inicializar banco de dados
    await database.init_database()

    # Criar jogadores de teste
    players = [
        {"discord_id": "123456789", "discord_username": "Player1", "lichess_username": "player1_lichess"},
        {"discord_id": "987654321", "discord_username": "Player2", "lichess_username": "player2_lichess"},
        {"discord_id": "111111111", "discord_username": "Player3", "lichess_username": "player3_lichess"},
        {"discord_id": "222222222", "discord_username": "Player4", "lichess_username": "player4_lichess"},
    ]

    for player in players:
        await database.register_player(
            player["discord_id"],
            player["discord_username"],
            player["lichess_username"]
        )

    print("✅ Jogadores criados")

    # Criar torneio com limite de 1 rodada
    tournament_id = await database.create_tournament(
        name="Torneio Limite Rodadas",
        description="Torneio para testar limite de rodadas",
        mode="blitz",
        time_control="blitz",
        max_participants=4,
        min_participants=2,
        created_by="123456789",
        is_automatic=True,
        rated=True,
        numero_de_rodadas=1  # Limite de 1 rodada
    )

    print(f"✅ Torneio criado com ID: {tournament_id} (limite: 1 rodada)")

    # Inscrever jogadores
    for player in players:
        success, message = await database.join_tournament(tournament_id, player["discord_id"])
        if success:
            print(f"✅ {player['discord_username']} entrou no torneio")
        else:
            print(f"❌ Erro ao inscrever {player['discord_username']}: {message}")

    # Iniciar torneio
    success, message = await database.start_tournament(tournament_id)
    if success:
        print("✅ Torneio iniciado")
    else:
        print(f"❌ Erro ao iniciar torneio: {message}")
        return

    # Simular resultados das partidas da primeira rodada
    matches = await database.get_tournament_matches(tournament_id, 1)
    print(f"📊 Partidas da rodada 1: {len(matches)}")

    for i, match in enumerate(matches):
        winner_id = match['player1_id'] if i % 2 == 0 else match['player2_id']
        await database.update_tournament_match_winner(tournament_id, match['round_number'], match['match_number'], winner_id)
        print(f"✅ Partida {match['id']} finalizada - Vencedor: {winner_id}")

    # Verificar se rodada foi completada
    round_completed = await database.check_round_completion(tournament_id, 1)
    print(f"🔄 Rodada 1 completada: {round_completed}")

    if round_completed:
        # Tentar avançar para próxima rodada - deve finalizar o torneio devido ao limite
        success, message = await database.advance_tournament_round(tournament_id)
        print(f"📢 Resultado do avanço: {message}")

        # Verificar status do torneio
        tournament = await database.get_tournament(tournament_id)
        print(f"🏆 Status do torneio: {tournament['status']}")
        if tournament['winner_id']:
            print(f"👑 Vencedor: {tournament['winner_id']}")

    # Verificar standings finais
    standings = await database.get_tournament_standings(tournament_id)
    print("🏆 Standings finais:")
    for i, standing in enumerate(standings, 1):
        print(f"{i}. {standing['discord_username']}: {standing['points']} pontos")

    print("🧪 Teste concluído!")

if __name__ == "__main__":
    asyncio.run(test_tournament_rounds_limit())
