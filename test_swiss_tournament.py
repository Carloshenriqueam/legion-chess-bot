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

class TestSwissTournamentCreation:
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

    async def test_swiss_tournament_api_integration(self):
        """Test the Swiss tournament API integration"""
        print("\n🔧 Testing Swiss tournament API integration...")

        # Test 1: Missing LICHESS_TOKEN
        with patch.dict(os.environ, {}, clear=True):
            result = await lichess_api.create_lichess_swiss_tournament(
                name="Test Swiss",
                description="Test description",
                clock_time=10,
                clock_increment=0,
                nb_rounds=5,
                rated=True,
                variant="standard"
            )
            passed = result is None
            error = lichess_api.get_last_create_game_error()
            self.log_test("Missing LICHESS_TOKEN", passed, f"Error: {error}")

        # Test 2: Invalid parameters (nb_rounds too low)
        with patch.dict(os.environ, {'LICHESS_TOKEN': 'fake_token'}):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value = mock_session

                mock_response = AsyncMock()
                mock_response.status = 400
                mock_response.text = AsyncMock(return_value='{"error": "Invalid number of rounds"}')

                # Create a proper async context manager mock
                mock_context = AsyncMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_response)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_session.post.return_value = mock_context

                result = await lichess_api.create_lichess_swiss_tournament(
                    name="Test Swiss",
                    nb_rounds=1,  # Invalid: too low
                    clock_time=10,
                    clock_increment=0,
                    rated=True,
                    variant="standard"
                )
                passed = result is None
                error = lichess_api.get_last_create_game_error()
                self.log_test("Invalid parameters (nb_rounds too low)", passed, f"Error: {error}")

        # Test 3: Successful creation
        with patch.dict(os.environ, {'LICHESS_TOKEN': 'fake_token'}):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value = mock_session

                mock_response = AsyncMock()
                mock_response.status = 200
                mock_response.json = AsyncMock(return_value={'id': 'test_swiss_id_123'})

                # Create a proper async context manager mock
                mock_context = AsyncMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_response)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_session.post.return_value = mock_context

                result = await lichess_api.create_lichess_swiss_tournament(
                    name="Test Swiss Tournament",
                    description="A test Swiss tournament",
                    clock_time=10,
                    clock_increment=5,
                    nb_rounds=5,
                    rated=True,
                    variant="standard",
                    min_rating=1500,
                    max_rating=2000,
                    chat_for=10
                )
                passed = result == 'test_swiss_id_123'
                self.log_test("Successful Swiss tournament creation", passed, f"Swiss ID: {result}")

        # Test 4: API error handling
        with patch.dict(os.environ, {'LICHESS_TOKEN': 'fake_token'}):
            with patch('aiohttp.ClientSession') as mock_session_class:
                mock_session = AsyncMock()
                mock_session_class.return_value = mock_session

                mock_response = AsyncMock()
                mock_response.status = 500
                mock_response.text = AsyncMock(return_value='Internal Server Error')

                # Create a proper async context manager mock
                mock_context = AsyncMock()
                mock_context.__aenter__ = AsyncMock(return_value=mock_response)
                mock_context.__aexit__ = AsyncMock(return_value=None)
                mock_session.post.return_value = mock_context

                result = await lichess_api.create_lichess_swiss_tournament(
                    name="Test Swiss",
                    clock_time=10,
                    clock_increment=0,
                    nb_rounds=5,
                    rated=True,
                    variant="standard"
                )
                passed = result is None
                error = lichess_api.get_last_create_game_error()
                self.log_test("API error handling", passed, f"Error: {error}")

    async def test_swiss_tournament_command_validations(self):
        """Test the /criar_torneio_suico_lichess command validations"""
        print("\n🔧 Testing Swiss tournament command validations...")

        # Mock interaction
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        # Test 1: Empty name validation
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="",  # Empty name
            tempo_inicial=10,
            incremento=0,
            numero_rodadas=5,
            rated=True,
            variante="standard"
        )
        interaction.followup.send.assert_called_with("❌ O nome do torneio é obrigatório.", ephemeral=True)
        self.log_test("Empty name validation", True)

        # Test 2: Invalid clock time (too low)
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=-1,  # Invalid
            incremento=0,
            numero_rodadas=5,
            rated=True,
            variante="standard"
        )
        interaction.followup.send.assert_called_with("❌ Tempo inicial deve ser entre 0 e 180 minutos.", ephemeral=True)
        self.log_test("Invalid clock time (too low)", True)

        # Test 3: Invalid clock time (too high)
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=200,  # Invalid
            incremento=0,
            numero_rodadas=5,
            rated=True,
            variante="standard"
        )
        interaction.followup.send.assert_called_with("❌ Tempo inicial deve ser entre 0 e 180 minutos.", ephemeral=True)
        self.log_test("Invalid clock time (too high)", True)

        # Test 4: Invalid increment (too high)
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=10,
            incremento=200,  # Invalid
            numero_rodadas=5,
            rated=True,
            variante="standard"
        )
        interaction.followup.send.assert_called_with("❌ Incremento deve ser entre 0 e 180 segundos.", ephemeral=True)
        self.log_test("Invalid increment (too high)", True)

        # Test 5: Invalid number of rounds (too low)
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=10,
            incremento=0,
            numero_rodadas=2,  # Invalid
            rated=True,
            variante="standard"
        )
        interaction.followup.send.assert_called_with("❌ Número de rodadas deve ser entre 3 e 20.", ephemeral=True)
        self.log_test("Invalid number of rounds (too low)", True)

        # Test 6: Invalid variant
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=10,
            incremento=0,
            numero_rodadas=5,
            rated=True,
            variante="invalid_variant"  # Invalid
        )
        interaction.followup.send.assert_called_with("❌ Variante inválida. Use: standard, chess960, crazyhouse, antichess, atomic, horde, kingOfTheHill, racingKings, threeCheck.", ephemeral=True)
        self.log_test("Invalid variant", True)

        # Test 7: Invalid chat setting
        interaction.reset_mock()
        await self.cog.criar_torneio_suico_lichess.callback(
            self.cog,
            interaction=interaction,
            nome="Test Swiss",
            tempo_inicial=10,
            incremento=0,
            numero_rodadas=5,
            rated=True,
            variante="standard",
            chat_para=5  # Invalid
        )
        interaction.followup.send.assert_called_with("❌ Chat deve ser 0 (ninguém), 10 (membros) ou 20 (todos).", ephemeral=True)
        self.log_test("Invalid chat setting", True)

    async def test_swiss_tournament_command_success(self):
        """Test successful Swiss tournament command execution"""
        print("\n🔧 Testing Swiss tournament command success...")

        # Mock interaction
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        # Mock the API call to succeed
        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = 'test_swiss_id_456'

            await self.cog.criar_torneio_suico_lichess.callback(
                self.cog,
                interaction=interaction,
                nome="Test Swiss Tournament",
                descricao="A test Swiss tournament",
                tempo_inicial=15,
                incremento=10,
                numero_rodadas=7,
                rated=False,
                variante="chess960",
                chat_para=20,
                rating_minimo=1200,
                rating_maximo=1800
            )

            # Verify the API was called with correct parameters
            mock_create.assert_called_once_with(
                name="Test Swiss Tournament",
                description="A test Swiss tournament",
                clock_time=15,
                clock_increment=10,
                nb_rounds=7,
                rated=False,
                variant="chess960",
                position="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                password="",
                team_id="",
                min_rating=1200,
                max_rating=1800,
                nb_rated_games=None,
                chat_for=20,
                allow_list="",
                starts_at=None
            )

            # Verify embed was sent
            interaction.followup.send.assert_called_once()
            call_args = interaction.followup.send.call_args
            embed = call_args[1]['embed']

            passed = (embed.title == "🏆 Torneio Suíço Criado no Lichess!" and
                     "test_swiss_id_456" in embed.fields[0].value)
            self.log_test("Successful Swiss tournament command", passed, f"Embed title: {embed.title}")

    async def test_swiss_tournament_command_failure(self):
        """Test Swiss tournament command failure handling"""
        print("\n🔧 Testing Swiss tournament command failure...")

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

                self.log_test("Swiss tournament command failure handling", True)

    async def test_edge_cases(self):
        """Test edge cases and boundary conditions"""
        print("\n🔧 Testing edge cases...")

        # Test with extreme values within limits
        interaction = Mock()
        interaction.response = AsyncMock()
        interaction.followup = AsyncMock()

        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = 'edge_case_swiss_id'

            # Test maximum rounds
            await self.cog.criar_torneio_suico_lichess.callback(
                self.cog,
                interaction=interaction,
                nome="Edge Case Swiss",
                tempo_inicial=180,  # Max time
                incremento=180,  # Max increment
                numero_rodadas=20,  # Max rounds
                rated=True,
                variante="threeCheck",
                chat_para=20  # Max chat
            )

            mock_create.assert_called_with(
                name="Edge Case Swiss",
                description="",
                clock_time=180,
                clock_increment=180,
                nb_rounds=20,
                rated=True,
                variant="threeCheck",
                position="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                password="",
                team_id="",
                min_rating=None,
                max_rating=None,
                nb_rated_games=None,
                chat_for=20,
                allow_list="",
                starts_at=None
            )

            self.log_test("Edge cases (maximum values)", True)

    async def run_all_tests(self):
        """Run all Swiss tournament tests"""
        print("🧪 Starting comprehensive Swiss tournament creation tests...\n")

        print("1. Testing API integration...")
        await self.test_swiss_tournament_api_integration()

        print("\n2. Testing command validations...")
        await self.test_swiss_tournament_command_validations()

        print("\n3. Testing command success...")
        await self.test_swiss_tournament_command_success()

        print("\n4. Testing command failure...")
        await self.test_swiss_tournament_command_failure()

        print("\n5. Testing edge cases...")
        await self.test_edge_cases()

        print("\n" + "="*50)
        print("📊 SWISS TOURNAMENT TEST RESULTS SUMMARY")
        print("="*50)

        passed = sum(1 for result in self.test_results if result.startswith("✅"))
        failed = sum(1 for result in self.test_results if result.startswith("❌"))
        total = len([r for r in self.test_results if not r.startswith("   ")])

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(".1f")

        if failed == 0:
            print("🎉 All Swiss tournament tests passed!")
        else:
            print("⚠️  Some tests failed. Please review the results above.")

        print("\nDetailed Results:")
        for result in self.test_results:
            print(result)

async def main():
    tester = TestSwissTournamentCreation()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
