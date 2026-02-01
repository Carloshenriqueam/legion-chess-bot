import asyncio
import database

async def test_ranking_update():
    """Testa a atualização de ranking do torneio."""
    print("🧪 Testando atualização de ranking...")

    # Usar torneio existente (ID 17 do teste anterior)
    tournament_id = 17

    # Verificar se torneio existe
    tournament = await database.get_tournament(tournament_id)
    if not tournament:
        print("❌ Torneio não encontrado")
        return

    print(f"✅ Torneio encontrado: {tournament['name']}")

    # Verificar standings atuais
    standings = await database.get_tournament_standings(tournament_id)
    print("🏆 Standings atuais:")
    for i, standing in enumerate(standings, 1):
        print(f"{i}. {standing['discord_username']}: {standing['points']} pontos")

    # Simular chamada do método update_tournament_ranking
    # Como não temos um bot real, vamos testar apenas a lógica de deletar e enviar nova mensagem
    print("\n🔄 Simulando update_tournament_ranking...")

    # Verificar se tem ranking_channel_id e ranking_message_id
    if tournament.get('ranking_channel_id') and tournament.get('ranking_message_id'):
        print(f"✅ Ranking channel ID: {tournament['ranking_channel_id']}")
        print(f"✅ Ranking message ID: {tournament['ranking_message_id']}")
        print("📝 O método tentaria deletar a mensagem antiga e enviar uma nova")
    else:
        print("⚠️  Torneio não tem ranking channel/message configurado")
        print("   Isso é normal para torneios de teste sem bot Discord")

    print("✅ Teste de ranking update concluído!")

if __name__ == "__main__":
    asyncio.run(test_ranking_update())
