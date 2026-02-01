# Patch para Backend - legionchess-new

## Adição ao app.py (Flask Backend)

Adicione o seguinte código ao seu `app.py` (ou arquivo de rotas):

```python
from database import get_ranking_by_mode_for_api

# Endpoint de Ranking
@app.route('/api/ranking/<mode>', methods=['GET'])
async def get_ranking(mode):
    """
    Retorna o ranking de uma modalidade específica com dados de avatares.
    
    Modalidades suportadas: bullet, blitz, rapid, classic
    
    Resposta:
    {
      "jogadores": [
        {
          "id_discord": "123456789",
          "nome": "PlayerName",
          "avatar_hash": "a_1234567890abcdef",
          "rating": 1500,
          "vitorias": 10,
          "derrotas": 5,
          "empates": 2,
          "partidas_jogadas": 17
        },
        ...
      ],
      "ultimo_update": "2026-01-23T15:30:00.123456"
    }
    """
    try:
        # Validar modo
        if mode not in ['bullet', 'blitz', 'rapid', 'classic']:
            return jsonify({'error': 'Modo inválido. Use: bullet, blitz, rapid ou classic'}), 400
        
        # Buscar dados do bot (database do legion-chess-bot)
        import sys
        sys.path.insert(0, r'C:\Users\carlu\legion-chess-bot')
        from database import get_ranking_by_mode_for_api
        
        ranking_data = await get_ranking_by_mode_for_api(mode)
        
        return jsonify(ranking_data), 200
    except Exception as e:
        app.logger.error(f"Erro ao buscar ranking {mode}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500
```

## Importações Necessárias

No topo do seu `app.py`, adicione:

```python
import sys
import asyncio
from flask import jsonify, Flask
```

## Configuração de Caminhos

O bot está em: `C:\Users\carlu\legion-chess-bot`
O site está em: `C:\Users\carlu\Desktop\legionchess-new`

O backend do novo site precisa importar as funções do bot.

### Opção 1: Cópia do database.py
Copie as funções de database para um arquivo compartilhado.

### Opção 2: Importação Direta (Recomendado)
```python
import sys
sys.path.insert(0, r'C:\Users\carlu\legion-chess-bot')
from database import get_ranking_by_mode_for_api
```

## Como o Frontend Processa

O site novo (`legionchess-new`) recebe a resposta e processa:

```typescript
// Em App.tsx
const response = await fetch(`${API_URL}/ranking/${mode}`);
const data = await response.json();

// Para cada jogador:
const jogadores = data.jogadores.map(j => {
  let avatarUrl: string | undefined = j.avatar_url;

  if (!avatarUrl) {
    if (j.avatar_hash) {
      // Montar URL do Discord
      avatarUrl = `https://cdn.discordapp.com/avatars/${j.id_discord}/${j.avatar_hash}.png`;
    } else {
      // Avatar padrão
      const defaultIndex = parseInt(j.id_discord || '0') % 5;
      avatarUrl = `https://cdn.discordapp.com/embed/avatars/${defaultIndex}.png`;
    }
  }

  return {
    id_discord: j.id_discord,
    nome: j.nome,
    avatar_url: avatarUrl,
    avatar_hash: j.avatar_hash,
    rating: j.rating,
    // ... mais dados
  };
});
```

## Teste

```bash
# Terminal PowerShell
curl http://localhost:5000/api/ranking/blitz
```

Deve retornar algo como:
```json
{
  "jogadores": [
    {
      "id_discord": "123456789",
      "nome": "carloshenri",
      "avatar_hash": "70da9fe56bbb84efa611f9afe494df55",
      "rating": 1500,
      "vitorias": 10,
      "derrotas": 5,
      "empates": 2,
      "partidas_jogadas": 17
    }
  ],
  "ultimo_update": "2026-01-23T15:30:00.123456"
}
```

## Observações Importantes

1. **Avatar URL**: O Discord hospeda em: `https://cdn.discordapp.com/avatars/{id}/{hash}.png`
2. **Avatar Hash**: Salvo no banco quando o bot sincroniza
3. **Fallback**: Se não tiver avatar customizado, usa padrão do Discord
4. **CORS**: Certifique-se que o backend tem CORS configurado se o frontend e backend estão em portas diferentes

## Sincronização de Avatares

Para sincronizar novamente:
```bash
cd C:\Users\carlu\legion-chess-bot
C:\Users\carlu\legion-chess-bot\venv\Scripts\python.exe sync_avatars.py
```

Isto atualiza o `avatar_hash` de todos os jogadores baseado no Discord atual.

