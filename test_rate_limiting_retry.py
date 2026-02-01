import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from lichess_api import create_lichess_tournament, create_lichess_swiss_tournament, get_last_create_game_error

class TestRateLimitingRetry(unittest.TestCase):

    def setUp(self):
        self.test_token = "test_token_123"
        self.test_name = "Test Tournament"

    @patch.dict('os.environ', {'LICHESS_TOKEN': 'test_token_123'})
    @patch('lichess_api.aiohttp.ClientSession')
    async def test_create_lichess_tournament_retry_on_429(self, mock_session_class):
        """Testa retry com backoff exponencial para torneios regulares quando há rate limiting"""
        # Configurar mock da sessão
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Simular 2 tentativas com 429, depois sucesso na 3ª tentativa
        mock_responses = [
            AsyncMock(status=429, text=AsyncMock(return_value='{"error":"Too many requests"}')),
            AsyncMock(status=429, text=AsyncMock(return_value='{"error":"Too many requests"}')),
            AsyncMock(status=200, json=AsyncMock(return_value={'id': 'test_tournament_id'}))
        ]

        mock_session.post.side_effect = mock_responses

        # Executar função
        result = await create_lichess_tournament(self.test_name)

        # Verificações
        self.assertEqual(result, 'test_tournament_id')
        self.assertEqual(mock_session.post.call_count, 3)  # 3 tentativas

        # Verificar se sleep foi chamado com delays exponenciais (5, 10 segundos)
        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            # Re-executar para capturar sleeps
            mock_session.post.reset_mock()
            mock_session.post.side_effect = mock_responses
            await create_lichess_tournament(self.test_name)

            # Verificar delays: 5s na primeira retry, 10s na segunda
            expected_delays = [5, 10]
            actual_delays = [call[0][0] for call in mock_sleep.call_args_list]
            self.assertEqual(actual_delays, expected_delays)

    @patch.dict('os.environ', {'LICHESS_TOKEN': 'test_token_123'})
    @patch('lichess_api.aiohttp.ClientSession')
    async def test_create_lichess_swiss_tournament_retry_on_429(self, mock_session_class):
        """Testa retry com backoff exponencial para torneios suíços quando há rate limiting"""
        # Configurar mock da sessão
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Simular 1 tentativa com 429, depois sucesso na 2ª tentativa
        mock_responses = [
            AsyncMock(status=429, text=AsyncMock(return_value='{"error":"Too many requests"}')),
            AsyncMock(status=200, json=AsyncMock(return_value={'id': 'test_swiss_id'}))
        ]

        mock_session.post.side_effect = mock_responses

        # Executar função
        result = await create_lichess_swiss_tournament(self.test_name)

        # Verificações
        self.assertEqual(result, 'test_swiss_id')
        self.assertEqual(mock_session.post.call_count, 2)  # 2 tentativas

    @patch.dict('os.environ', {'LICHESS_TOKEN': 'test_token_123'})
    @patch('lichess_api.aiohttp.ClientSession')
    async def test_create_lichess_tournament_max_retries_exceeded(self, mock_session_class):
        """Testa comportamento quando rate limiting persiste após todas as tentativas"""
        # Configurar mock da sessão
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Simular sempre 429 (5 tentativas)
        mock_response = AsyncMock(status=429, text=AsyncMock(return_value='{"error":"Too many requests"}'))
        mock_session.post.return_value.__aenter__.return_value = mock_response

        # Executar função
        result = await create_lichess_tournament(self.test_name)

        # Verificações
        self.assertIsNone(result)
        self.assertEqual(mock_session.post.call_count, 5)  # Máximo de tentativas

        # Verificar mensagem de erro
        error_msg = get_last_create_game_error()
        self.assertIn("Rate limiting persistente", error_msg)

    @patch.dict('os.environ', {'LICHESS_TOKEN': 'test_token_123'})
    @patch('lichess_api.aiohttp.ClientSession')
    async def test_create_lichess_tournament_success_first_try(self, mock_session_class):
        """Testa que não há retry quando a primeira tentativa é bem-sucedida"""
        # Configurar mock da sessão
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Simular sucesso na primeira tentativa
        mock_response = AsyncMock(status=200, json=AsyncMock(return_value={'id': 'test_tournament_id'}))
        mock_session.post.return_value.__aenter__.return_value = mock_response

        # Executar função
        result = await create_lichess_tournament(self.test_name)

        # Verificações
        self.assertEqual(result, 'test_tournament_id')
        self.assertEqual(mock_session.post.call_count, 1)  # Apenas 1 tentativa

    @patch.dict('os.environ', {'LICHESS_TOKEN': 'test_token_123'})
    @patch('lichess_api.aiohttp.ClientSession')
    async def test_create_lichess_tournament_other_errors_no_retry(self, mock_session_class):
        """Testa que outros erros (não 429) não acionam retry"""
        # Configurar mock da sessão
        mock_session = AsyncMock()
        mock_session_class.return_value.__aenter__.return_value = mock_session

        # Simular erro 400 (bad request)
        mock_response = AsyncMock(status=400, text=AsyncMock(return_value='{"error":"Invalid parameters"}'))
        mock_session.post.return_value.__aenter__.return_value = mock_response

        # Executar função
        result = await create_lichess_tournament(self.test_name)

        # Verificações
        self.assertIsNone(result)
        self.assertEqual(mock_session.post.call_count, 1)  # Apenas 1 tentativa (sem retry)

        # Verificar mensagem de erro
        error_msg = get_last_create_game_error()
        self.assertIn("Parâmetros inválidos", error_msg)

if __name__ == '__main__':
    # Executar testes
    unittest.main()
