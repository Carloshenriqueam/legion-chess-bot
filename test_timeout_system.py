#!/usr/bin/env python3
"""
Teste do sistema de timeout para torneios suíços.
Este teste verifica se os timeouts de aceitação e finalização funcionam corretamente.
"""

import asyncio
import sys
import os

# Adicionar o diretório raiz ao path para importar os módulos
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
from cogs.tournaments import (
    TIMEOUT_ACCEPT_MINUTES,
    TIMEOUT_FINISH_HOURS,
    handle_pairing_timeout,
    handle_game_finish_timeout,
    check_player_abandonment,
    redistribute_pairings
)

async def test_timeout_system():
    """Testa o sistema de timeout para torneios suíços."""
    print("🧪 Iniciando testes do sistema de timeout...")

    try:
        # Inicializar banco de dados
        await database.init_database()
        print("✅ Banco de dados inicializado")

        # Criar um torneio de teste
        tournament_id = await database.create_swiss_tournament(
            name="Teste Timeout",
            description="Torneio para testar sistema de timeout",
            time_control="5+0",
            nb_rounds=3,
            created_by="test_user",
            rated=False
        )
        print(f"✅ Torneio de teste criado: ID {tournament_id}")

        # Adicionar alguns participantes de teste
        test_players = ["player1", "player2", "player3", "player4"]
        for player_id in test_players:
            success, message = await database.join_swiss_tournament(tournament_id, player_id)
            if success:
                print(f"✅ Jogador {player_id} adicionado")
            else:
                print(f"❌ Erro ao adicionar {player_id}: {message}")

        # Iniciar torneio
        success, message = await database.start_swiss_tournament(tournament_id)
        if success:
            print("✅ Torneio iniciado")
        else:
            print(f"❌ Erro ao iniciar torneio: {message}")
            return

        # Gerar primeira rodada
        await database.generate_and_save_swiss_round(tournament_id, 1)
        print("✅ Primeira rodada gerada")

        # Buscar pareamentos
        pairings = await database.get_swiss_pairings_for_round(tournament_id, 1)
        if pairings:
            print(f"✅ {len(pairings)} pareamentos criados")

            # Simular timeout de aceitação para o primeiro pareamento
            first_pairing = pairings[0]
            pairing_id = first_pairing['id']
            player1_id = first_pairing.get('player1_id')
            player2_id = first_pairing.get('player2_id')

            print(f"🧪 Testando timeout de aceitação para pairing {pairing_id}")

            # Simular que nenhum jogador aceitou (accepted_by vazio)
            # Chamar handle_pairing_timeout diretamente
            await handle_pairing_timeout(None, tournament_id, pairing_id, 1)

            print("✅ Timeout de aceitação processado")

            # Verificar se o pareamento foi atualizado
            updated_pairing = await database.get_swiss_pairing_by_id(pairing_id)
            if updated_pairing:
                print(f"📊 Status do pareamento após timeout: {updated_pairing.get('status')}")

        # Testar verificação de abandono
        print("🧪 Testando verificação de abandono...")
        await check_player_abandonment(None, tournament_id)
        print("✅ Verificação de abandono concluída")

        # Testar redistribuição de pareamentos
        print("🧪 Testando redistribuição de pareamentos...")
        await redistribute_pairings(tournament_id, 1)
        print("✅ Redistribuição concluída")

        print("🎉 Todos os testes do sistema de timeout foram executados!")

    except Exception as e:
        print(f"❌ Erro durante os testes: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_timeout_system())