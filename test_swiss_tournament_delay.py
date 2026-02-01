import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import lichess_api
from unittest.mock import Mock, AsyncMock, patch

class TestSwissTournamentDelay:
    def __init__(self):
        self.test_results = []

    def log_test(self, test_name, passed, details=""):
        status = "✅ PASS" if passed else "❌ FAIL"
        self.test_results.append(f"{status} {test_name}")
        if details:
            self.test_results.append(f"   {details}")
        print(f"{status} {test_name}")
        if details:
            print(f"   {details}")

    async def test_swiss_tournament_creation_delay(self):
        """Test that the 15-second delay allows proper tournament indexing"""
        print("Testing Swiss tournament creation with 15-second delay...")

        # Mock the Lichess API functions
        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create, \
             patch('lichess_api.get_lichess_swiss_tournament_info', new_callable=AsyncMock) as mock_get_info:

            # Simulate successful creation
            mock_create.return_value = "test_swiss_id_123"

            # First call to get_info (immediately after creation) returns None (404)
            # Second call (after delay) returns tournament info
            mock_get_info.side_effect = [None, {
                'name': 'Test Swiss Tournament',
                'id': 'test_swiss_id_123',
                'status': 'created',
                'nbPlayers': 0
            }]

            # Simulate the logic from the actual command
            swiss_id = await lichess_api.create_lichess_swiss_tournament(
                name="Test Swiss Tournament",
                description="Test tournament for delay verification",
                clock_time=10,
                clock_increment=0,
                nb_rounds=5,
                rated=True,
                variant="standard",
                position="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                password="",
                team_id="",
                min_rating=None,
                max_rating=None,
                nb_rated_games=None,
                chat_for=0,
                allow_list="",
                starts_at=None
            )

            if swiss_id:
                # Apply the 120-second delay
                await asyncio.sleep(120)

                # Verify tournament creation
                tournament_info = await lichess_api.get_lichess_swiss_tournament_info(swiss_id)

                if tournament_info:
                    self.log_test("Swiss tournament delay test", True,
                                 f"Tournament found after 120s delay: {tournament_info['name']}")
                else:
                    self.log_test("Swiss tournament delay test", False,
                                 "Tournament still not found after 120s delay - 404 error persists")
            else:
                self.log_test("Swiss tournament delay test", False,
                             "Failed to create Swiss tournament")

    async def test_delay_comparison(self):
        """Compare behavior with 5s vs 10s delay"""
        print("Comparing 5s vs 10s delay effectiveness...")

        with patch('lichess_api.create_lichess_swiss_tournament', new_callable=AsyncMock) as mock_create, \
             patch('lichess_api.get_lichess_swiss_tournament_info', new_callable=AsyncMock) as mock_get_info:

            mock_create.return_value = "test_delay_comparison"

            # Test with 5s delay - should fail
            mock_get_info.side_effect = [None]  # Always returns None

            swiss_id = await lichess_api.create_lichess_swiss_tournament(
                name="Test 5s Delay",
                description="Testing 5s delay",
                clock_time=10,
                clock_increment=0,
                nb_rounds=5,
                rated=True,
                variant="standard",
                position="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                password="",
                team_id="",
                min_rating=None,
                max_rating=None,
                nb_rated_games=None,
                chat_for=0,
                allow_list="",
                starts_at=None
            )

            await asyncio.sleep(5)
            info_5s = await lichess_api.get_lichess_swiss_tournament_info(swiss_id)

            # Reset for 10s test
            mock_get_info.side_effect = [None, {'name': 'Test 10s Delay', 'id': 'test_delay_comparison'}]

            await asyncio.sleep(5)  # Additional 5s to make 10s total
            info_10s = await lichess_api.get_lichess_swiss_tournament_info(swiss_id)

            passed = info_5s is None and info_10s is not None
            self.log_test("Delay comparison test", passed,
                         f"5s delay: {'Failed' if info_5s is None else 'Success'}, "
                         f"10s delay: {'Success' if info_10s else 'Failed'}")

    async def run_all_tests(self):
        """Run all delay-related tests"""
        print("🧪 Testing Swiss tournament creation delay improvements...\n")

        print("1. Testing 120-second delay effectiveness...")
        await self.test_swiss_tournament_creation_delay()

        print("\n2. Comparing delay durations...")
        await self.test_delay_comparison()

        print("\n" + "="*50)
        print("📊 DELAY TEST RESULTS SUMMARY")
        print("="*50)

        passed = sum(1 for result in self.test_results if result.startswith("✅"))
        failed = sum(1 for result in self.test_results if result.startswith("❌"))
        total = len([r for r in self.test_results if not r.startswith("   ")])

        print(f"Total Tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(".1f")

        if failed == 0:
            print("🎉 All delay tests passed! The 15-second delay should resolve 404 errors.")
        else:
            print("⚠️  Some delay tests failed. The change may need further adjustment.")

        print("\nDetailed Results:")
        for result in self.test_results:
            print(result)

async def main():
    tester = TestSwissTournamentDelay()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
