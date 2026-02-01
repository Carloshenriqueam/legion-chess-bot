import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import database
import lichess_api
from cogs.tournaments import Tournaments
from unittest.mock import Mock, AsyncMock, patch
import discord
from discord import app_commands
import aiohttp

class TestSwissTournamentVerification:
    def __init__(self):
        self.bot = Mock()
        self.cog = Tournaments(self.bot)
        self.test_results = []

    def log_test(self, test_name, passed, details=""):
        status = "✅ PASS" if passed else "❌ FAIL"
        self.test_results.append(f"{status} {test_name}")
        if details:
            self.test_results.append(f"   {details}")
        print(f"{status} {test_name}")
        if details:
            print(f"   {details}")

    async def test_verification_success(self):
        """Test successful tournament creation with verification"""
        print("\n🔧 Testing successful Swiss tournament creation with verification...")

        # Mock interaction
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        # Mock the API calls
        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            with patch('lichess_api.get_lichess_swiss_tournament_info', new_callable=AsyncMock) as mock_verify:
                mock_create.return_value = 'test_swiss_id_123'
                mock_verify.return_value = {'id': 'test_swiss_id_123', 'name': 'Test Tournament'}

                await self.cog.criar_torneio_suico_lichess.callback(
                    self.cog,
                    interaction=interaction,
                    nome="Test Swiss Tournament",
                    tempo_inicial=10,
                    incremento=0,
                    numero_rodadas=5,
                    rated=True,
                    variante="standard"
                )

                # Verify API calls
                mock_create.assert_called_once()
                mock_verify.assert_called_once_with('test_swiss_id_123')

                # Verify success message was sent
                interaction.followup.send.assert_called_once()
                call_args = interaction.followup.send.call_args
                embed = call_args[1]['embed']

                passed = (embed.title == "🏆 Torneio Suíço Criado no Lichess!" and
                         "test_swiss_id_123" in embed.fields[0].value)
                self.log_test("Successful creation with verification", passed, f"Embed title: {embed.title}")

    async def test_verification_failure(self):
        """Test tournament creation where verification fails despite getting ID"""
        print("\n🔧 Testing Swiss tournament creation with verification failure...")

        # Mock interaction
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        # Mock the API calls - creation succeeds but verification fails
        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            with patch('lichess_api.get_lichess_swiss_tournament_info', new_callable=AsyncMock) as mock_verify:
                mock_create.return_value = 'test_swiss_id_456'
                mock_verify.return_value = None  # Verification fails

                await self.cog.criar_torneio_suico_lichess.callback(
                    self.cog,
                    interaction=interaction,
                    nome="Test Swiss Tournament",
                    tempo_inicial=10,
                    incremento=0,
                    numero_rodadas=5,
                    rated=True,
                    variante="standard"
                )

                # Verify API calls
                mock_create.assert_called_once()
                mock_verify.assert_called_once_with('test_swiss_id_456')

                # Verify error message was sent
                interaction.followup.send.assert_called_once_with(
                    "❌ Torneio suíço criado mas não encontrado na API do Lichess. ID: test_swiss_id_456",
                    ephemeral=True
                )

                self.log_test("Creation with verification failure", True)

    async def test_creation_failure_no_id(self):
        """Test tournament creation failure (no ID returned)"""
        print("\n🔧 Testing Swiss tournament creation failure (no ID)...")

        # Mock interaction
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        # Mock the API call to fail
        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = None

            with patch('lichess_api.get_last_create_game_error', return_value="Token inválido"):
                await self.cog.criar_torneio_suico_lichess.callback(
                    self.cog,
                    interaction=interaction,
                    nome="Test Swiss",
                    tempo_inicial=10,
                    incremento=0,
                    numero_rodadas=5,
                    rated=True,
                    variante="standard"
                )

                # Verify error message was sent
                interaction.followup.send.assert_called_once_with(
                    "❌ Falha ao criar torneio suíço no Lichess. Motivo: Token inválido",
                    ephemeral=True
                )

                self.log_test("Creation failure (no ID)", True)

    async def test_edge_cases(self):
        """Test edge cases in verification"""
        print("\n🔧 Testing edge cases in verification...")

        # Test with network error during verification
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            with patch('lichess_api.get_lichess_swiss_tournament_info', new_callable=AsyncMock) as mock_verify:
                mock_create.return_value = 'test_swiss_id_789'
                mock_verify.side_effect = aiohttp.ClientError("Network error")

                await self.cog.criar_torneio_suico_lichess.callback(
                    self.cog,
                    interaction=interaction,
                    nome="Test Swiss Tournament",
                    tempo_inicial=10,
                    incremento=0,
                    numero_rodadas=5,
                    rated=True,
                    variante="standard"
                )

                # Should still fail verification
                interaction.followup.send.assert_called_once_with(
                    "❌ Torneio suíço criado mas não encontrado na API do Lichess. ID: test_swiss_id_789",
                    ephemeral=True
                )

                self.log_test("Network error during verification", True)

    async def run_all_tests(self):
        """Run all verification tests"""
        print("🧪 Starting comprehensive Swiss tournament verification tests...\n")

        print("1. Testing successful creation with verification...")
        await self.test_verification_success()

        print("\n2. Testing creation with verification failure...")
        await self.test_verification_failure()

        print("\n3. Testing creation failure (no ID)...")
        await self.test_creation_failure_no_id()

        print("\n4. Testing edge cases...")
        await self.test_edge_cases()

        print("\n" + "="*50)
        print("📊 SWISS TOURNAMENT VERIFICATION TEST RESULTS SUMMARY")
        print("="*50)

        passed = sum(1 for result in self.test_results if result.startswith("✅"))
        failed = sum(1 for result in self.test_results if result.startswith("❌"))
        total = len([r for r in self.test_results if not r.startswith("   ")])

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(".1f")

        if failed == 0:
            print("🎉 All verification tests passed!")
        else:
            print("⚠️  Some tests failed. Please review the results above.")

        print("\nDetailed Results:")
        for result in self.test_results:
            print(result)

async def main():
    tester = TestSwissTournamentVerification()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
