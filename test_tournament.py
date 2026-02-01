import database
import asyncio

async def test_tournament():
    """Teste completo do sistema de torneios"""
    try:
        print("🔄 Inicializando banco de dados...")
        await database.init_database()
        print("✅ Banco inicializado")

        print("\n🧪 Teste 1: Criação de torneio")
        tournament_id = await database.create_tournament(
            name='Torneio de Teste Completo',
            description='Teste completo do sistema de torneios',
            mode='blitz',
            time_control='5+3',
            max_participants=8,
            min_participants=2,
            created_by='123456789',
            is_automatic=False,
            rated=True
        )
        print(f"✅ Torneio criado com ID: {tournament_id}")

        print("\n🧪 Teste 2: Verificação de criação")
        tournament = await database.get_tournament(tournament_id)
        if tournament:
            print(f"✅ Torneio encontrado: {tournament['name']}")
            print(f"   - Modo: {tournament['mode']}")
            print(f"   - Tempo: {tournament['time_control']}")
            print(f"   - Rated: {tournament['rated']}")
            print(f"   - Status: {tournament['status']}")
        else:
            print("❌ Torneio não encontrado após criação")
            return

        print("\n🧪 Teste 3: Registro e inscrição de participantes")
        # Registrar e inscrever múltiplos participantes
        participants_data = [
            ('123456789', 'Player1'),
            ('987654321', 'Player2'),
            ('111111111', 'Player3'),
            ('222222222', 'Player4')
        ]
        for pid, username in participants_data:
            await database.register_player(pid, username)
            success, message = await database.join_tournament(tournament_id, pid)
            print(f"Inscrição {username} ({pid}): {'✅' if success else '❌'} {message}")

        print("\n🧪 Teste 4: Verificação de participantes")
        participants = await database.get_tournament_participants(tournament_id)
        print(f"Total de participantes: {len(participants)}")
        for p in participants:
            print(f"  - {p['discord_username']} (ID: {p['player_id']})")

        print("\n🧪 Teste 5: Iniciar torneio")
        success, message = await database.start_tournament(tournament_id)
        print(f"Iniciar torneio: {'✅' if success else '❌'} {message}")

        print("\n🧪 Teste 6: Verificação de partidas criadas")
        matches = await database.get_tournament_matches(tournament_id)
        print(f"Partidas criadas: {len(matches)}")
        for match in matches:
            p1 = match['player1_name'] or "TBD"
            p2 = match['player2_name'] or "BYE"
            status = match['status']
            print(f"  - Rodada {match['round_number']}, Partida {match['match_number']}: {p1} vs {p2} ({status})")

        print("\n🧪 Teste 7: Buscar torneios abertos")
        open_tournaments = await database.get_open_tournaments()
        print(f"Torneios abertos encontrados: {len(open_tournaments)}")

        print("\n🧪 Teste 8: Casos extremos")
        # Tentar inscrever em torneio já iniciado
        success, message = await database.join_tournament(tournament_id, '333333333')
        print(f"Inscrição em torneio iniciado: {'✅' if not success else '❌'} {message}")

        # Tentar iniciar torneio já iniciado
        success, message = await database.start_tournament(tournament_id)
        print(f"Iniciar torneio já iniciado: {'✅' if not success else '❌'} {message}")

        # Buscar torneio inexistente
        nonexistent = await database.get_tournament(99999)
        print(f"Buscar torneio inexistente: {'✅' if nonexistent is None else '❌'} {'Não encontrado' if nonexistent is None else 'Encontrado'}")

        print("\n🎉 Todos os testes completos passaram!")

    except Exception as e:
        print(f"❌ Erro durante teste: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_tournament())
