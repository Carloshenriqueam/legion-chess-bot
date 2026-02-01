# Integração de Avatares - Guia de Configuração

## O Problema

O site novo (legionchess-new) tenta acessar os avatares dos jogadores do Discord através de:
1. `avatar_hash` armazenado no banco de dados
2. Construir URL: `https://cdn.discordapp.com/avatars/{id_discord}/{avatar_hash}.png`

Porém, o campo `avatar_hash` não existia na tabela `players`.

## A Solução

### 1. ✅ Coluna Adicionada
Adicionei a coluna `avatar_hash` na tabela `players` em `database.py`:
```python
if 'avatar_hash' not in existing_cols:
    cursor.execute("ALTER TABLE players ADD COLUMN avatar_hash TEXT")
```

### 2. ✅ Função de API Criada
Criei `get_ranking_by_mode_for_api()` que retorna dados formatados:
```json
{
  "jogadores": [
    {
      "id_discord": "123456789",
      "nome": "Player1",
      "avatar_hash": "a_1234567890",
      "rating": 1500,
      "vitorias": 10,
      "derrotas": 5,
      "empates": 2,
      "partidas_jogadas": 17
    }
  ],
  "ultimo_update": "2026-01-23T..."
}
```

### 3. 📝 Próximos Passos

#### A. Sincronizar Avatares (Execute)
```bash
python sync_avatars.py
```
Isto vai:
- Conectar ao Discord usando seu token
- Buscar o avatar de cada jogador
- Salvar o `avatar_hash` no banco de dados

#### B. Atualizar Backend (legionchess-new)
Crie/atualize o endpoint `/api/ranking/{mode}` no `app.py`:

```python
from database import get_ranking_by_mode_for_api

@app.route('/api/ranking/<mode>', methods=['GET'])
async def get_ranking(mode):
    try:
        # Validar modo
        if mode not in ['bullet', 'blitz', 'rapid', 'classic']:
            return {'error': 'Modo inválido'}, 400
        
        # Buscar dados do bot
        ranking_data = await get_ranking_by_mode_for_api(mode)
        
        return ranking_data, 200
    except Exception as e:
        return {'error': str(e)}, 500
```

#### C. Como o Site Acessa as Imagens
O site (`legionchess-new`) recebe os dados e processa assim:

```typescript
// Se avatar_hash existe, monta URL do Discord:
if (j.avatar_hash) {
  avatarUrl = `https://cdn.discordapp.com/avatars/${j.id_discord}/${j.avatar_hash}.png`;
} else {
  // Usa avatar padrão do Discord
  const defaultIndex = parseInt(j.id_discord || '0') % 5;
  avatarUrl = `https://cdn.discordapp.com/embed/avatars/${defaultIndex}.png`;
}
```

### 4. 📊 Verificar Dados

```bash
# Verificar se avatares foram sincronizados
python
>>> import sqlite3
>>> conn = sqlite3.connect('legion_chess.db')
>>> cursor = conn.cursor()
>>> cursor.execute("SELECT discord_username, avatar_hash FROM players LIMIT 5")
>>> for row in cursor.fetchall():
>>>     print(row)
```

## Estrutura dos Dados no Banco

```sql
-- Coluna adicionada à tabela players
ALTER TABLE players ADD COLUMN avatar_hash TEXT;

-- Exemplo de dados:
discord_id: "123456789"
discord_username: "Player1"
avatar_hash: "a_1234567890abcdef"
```

## URLs de Avatar Geradas

Com o `avatar_hash` preenchido, a URL fica assim:
```
https://cdn.discordapp.com/avatars/123456789/a_1234567890abcdef.png
```

Se não tiver `avatar_hash`, usa o padrão do Discord (sem ID de usuário):
```
https://cdn.discordapp.com/embed/avatars/0.png  (0-4 dependendo do ID)
```

## Próximas Ações

1. ✅ Coluna adicionada ao banco
2. ✅ Função de API criada
3. ⏳ **Execute `python sync_avatars.py` para sincronizar avatares**
4. ⏳ Atualize o backend do site novo com o endpoint `/api/ranking/{mode}`
5. ⏳ Teste a integração acessando: `http://localhost:5000/api/ranking/blitz`

## Troubleshooting

### "avatar_hash is NULL"
- Significa que `sync_avatars.py` ainda não foi executado
- Execute: `python sync_avatars.py`

### Imagens não carregam no site
1. Verifique se o Discord está retornando avatar (usuário pode não ter foto customizada)
2. Verifique o `avatar_hash` no banco: `SELECT * FROM players WHERE discord_username = 'PlayerName'`
3. Teste a URL diretamente no navegador

### Erro de conexão com Discord
- Verifique se `DISCORD_TOKEN` está no `.env`
- Verifique se o token é válido

