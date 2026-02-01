import asyncio
import database

async def test_tournament_with_byes():
    """Testa torneios com byes (número ímpar de participantes)."""
    print("🧪 Testando torneios com byes...")

    # Inicializar banco de dados
    await database.init_database()

    # Criar jogadores de teste
    players = [
        {"discord_id": "111111111", "discord_username": "Player1", "lichess_username": "player1_lichess"},
        {"discord_id": "222222222", "discord_username": "Player2", "lichess_username": "player2_lichess"},
        {"discord_id": "333333333", "discord_username": "Player3", "lichess_username": "player3_lichess"},
    ]

    for player in players:
        await database.register_player(
            player["discord_id"],
            player["discord_username"],
            player["lichess_username"]
        )

    print("✅ Jogadores criados")

    # Criar torneio com 3 participantes (ímpar)
    tournament_id = await database.create_tournament(
        name="Torneio com Bye Teste",
        description="Torneio para testar funcionalidade de byes",
        mode="blitz",
        time_control="5+3",
        max_participants=8,
        min_participants=2,
        created_by="111111111",
        is_automatic=False,
        rated=True
    )

    print(f"✅ Torneio criado com ID: {tournament_id}")

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

    # Verificar partidas criadas
    matches = await database.get_tournament_matches(tournament_id)
    print(f"📊 Partidas criadas: {len(matches)}")

    for match in matches:
        p1 = match['player1_name'] or "TBD"
        p2 = match['player2_name'] or "BYE"
        status = match['status']
        print(f"  - Rodada {match['round_number']}, Partida {match['match_number']}: {p1} vs {p2} ({status})")

    # Simular finalização da partida normal
    normal_match = next((m for m in matches if m['status'] == 'pending'), None)
    if normal_match:
        winner_id = normal_match['player1_id']
        await database.update_tournament_match_winner(tournament_id, normal_match['round_number'], normal_match['match_number'], winner_id)
        print(f"✅ Partida normal finalizada - Vencedor: {winner_id}")

    # Verificar se rodada foi completada (deve incluir o bye)
    round_completed = await database.check_round_completion(tournament_id, 1)
    print(f"🔄 Rodada 1 completada: {round_completed}")

    # Nota: advance_tournament_round é chamado automaticamente em update_tournament_match_winner
    # Não precisamos chamar manualmente aqui

    # Verificar standings
    standings = await database.get_tournament_standings(tournament_id)
    print("🏆 Standings atuais:")
    for i, standing in enumerate(standings, 1):
        print(f"{i}. {standing['discord_username']}: {standing['points']} pontos")

    # Verificar status do torneio
    tournament = await database.get_tournament(tournament_id)
    print(f"📊 Status do torneio: {tournament['status']}")
    if tournament['winner_id']:
        winner = await database.get_all_player_stats(tournament['winner_id'])
        print(f"🏆 Vencedor: {winner['discord_username'] if winner else 'N/A'}")

    print("🧪 Teste de torneio com byes concluído!")

if __name__ == "__main__":
    asyncio.run(test_tournament_with_byes())
