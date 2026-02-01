import asyncio
import database

async def test_discord_tournament_simulation():
    """Simula exatamente o que acontece no Discord com /criar_torneio e /avançar_torneio."""
    print("🧪 Simulando torneio do Discord...")

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

    # Simular /criar_torneio com numero_de_rodadas=2
    tournament_id = await database.create_tournament(
        name="Torneio Discord Simulado",
        description="Simulação do comando /criar_torneio",
        mode="blitz",
        time_control="3+0",
        max_participants=4,
        min_participants=4,
        created_by="123456789",
        is_automatic=True,  # Sempre automático
        rated=True,
        required_role_id=None,
        numero_de_rodadas=2  # Parâmetro fornecido pelo usuário
    )

    print(f"✅ Torneio criado com ID: {tournament_id} (numero_de_rodadas=2)")

    # Verificar se o numero_de_rodadas foi salvo corretamente
    tournament = await database.get_tournament(tournament_id)
    print(f"📋 Configuração do torneio: numero_de_rodadas={tournament.get('numero_de_rodadas')}")

    # Inscrever jogadores (simulando /participar_torneio)
    for player in players:
        success, message = await database.join_tournament(tournament_id, player["discord_id"])
        if success:
            print(f"✅ {player['discord_username']} entrou no torneio")
        else:
            print(f"❌ Erro ao inscrever {player['discord_username']}: {message}")

    # Simular /iniciar_torneio
    success, message = await database.start_tournament(tournament_id)
    if success:
        print("✅ Torneio iniciado")
    else:
        print(f"❌ Erro ao iniciar torneio: {message}")
        return

    # Verificar partidas criadas
    matches = await database.get_tournament_matches(tournament_id)
    print(f"📊 Total de partidas criadas: {len(matches)}")

    # Simular finalização das partidas da rodada 1
    round1_matches = [m for m in matches if m['round_number'] == 1]
    print(f"🎯 Rodada 1 - Partidas: {len(round1_matches)}")

    for match in round1_matches:
        # Simular que as partidas foram finalizadas (normalmente via tasks.py)
        winner_id = match['player1_id']  # Simular vitória do player1
        await database.update_tournament_match_winner(
            tournament_id, match['round_number'], match['match_number'], winner_id
        )
        print(f"✅ Partida {match['id']} finalizada - Vencedor: {winner_id}")

    # Verificar se rodada 1 está completa
    round1_complete = await database.check_round_completion(tournament_id, 1)
    print(f"🔄 Rodada 1 completa: {round1_complete}")

    if round1_complete:
        # Simular /avançar_torneio
        print("\n--- SIMULANDO /avançar_torneio ---")
        success, message = await database.advance_tournament_round(tournament_id)
        print(f"📢 Resultado do /avançar_torneio: {message}")

        if success:
            if "Torneio finalizado" in message:
                print("❌ TORNEIO FINALIZOU PREMATURAMENTE!")
                tournament = await database.get_tournament(tournament_id)
                print(f"🏆 Status: {tournament['status']}")
                return
            else:
                print("✅ Rodada avançada com sucesso")

                # Verificar se rodada 2 foi criada
                matches_after = await database.get_tournament_matches(tournament_id)
                round2_matches = [m for m in matches_after if m['round_number'] == 2]
                print(f"📊 Rodada 2 - Partidas criadas: {len(round2_matches)}")

                if round2_matches:
                    print("✅ Rodada 2 criada corretamente!")

                    # Simular finalização da rodada 2
                    for match in round2_matches:
                        winner_id = match['player1_id']
                        await database.update_tournament_match_winner(
                            tournament_id, match['round_number'], match['match_number'], winner_id
                        )
                        print(f"✅ Partida {match['id']} (Rodada 2) finalizada - Vencedor: {winner_id}")

                    # Verificar se rodada 2 está completa
                    round2_complete = await database.check_round_completion(tournament_id, 2)
                    print(f"🔄 Rodada 2 completa: {round2_complete}")

                    if round2_complete:
                        # Tentar avançar novamente - deve finalizar devido ao limite
                        print("\n--- SIMULANDO SEGUNDO /avançar_torneio ---")
                        success, message = await database.advance_tournament_round(tournament_id)
                        print(f"📢 Resultado do segundo /avançar_torneio: {message}")

                        tournament = await database.get_tournament(tournament_id)
                        print(f"🏆 Status final: {tournament['status']}")
                        if tournament['winner_id']:
                            print(f"👑 Vencedor: {tournament['winner_id']}")
                else:
                    print("❌ Rodada 2 não foi criada!")
        else:
            print(f"❌ Falha ao avançar rodada: {message}")

    # Verificar standings finais
    standings = await database.get_tournament_standings(tournament_id)
    print("\n🏆 Standings finais:")
    for i, standing in enumerate(standings, 1):
        print(f"{i}. {standing['discord_username']}: {standing['points']} pontos")

    print("🧪 Simulação concluída!")

if __name__ == "__main__":
    asyncio.run(test_discord_tournament_simulation())
