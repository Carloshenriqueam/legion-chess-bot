# Correção: Partidas não aparecendo no /historico

## Problema Identificado
As partidas finalizadas não estavam sendo salvas na tabela `game_history`, causando que o endpoint `/api/historico/<discord_id>` retornasse lista vazia.

## Causas Raiz

### 1. Recuperação incorreta de nomes de jogadores
No arquivo `tasks.py` (linhas 375-386), o código tentava acessar colunas `challenger_name` e `challenged_name` que **não existem** na tabela `challenges`:
```python
p1_name = ch.get('challenger_name')  # ❌ Coluna não existe
p2_name = ch.get('challenged_name')  # ❌ Coluna não existe
```

**Solução**: Buscar os nomes diretamente da tabela `players` usando os IDs dos jogadores.

### 2. Query de busca incompleta
A função `get_finished_games_to_process()` buscava apenas desafios com status `'accepted'`:
```python
WHERE c.status = 'accepted' AND c.game_url IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
```

Isso deixava de fora desafios que já tinham sido marcados como `'finished'` (e já tinham entrada em `matches`) mas ainda não tinham sido salvos em `game_history`.

**Solução**: Expandir a query para incluir desafios `'finished'` que ainda não têm registro em `game_history`:
```python
WHERE (
    -- Desafios aceitos que ainda não foram salvos em game_history
    (c.status = 'accepted' AND c.game_url IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id))
    OR
    -- Desafios finalizados que ainda não foram salvos em game_history
    (c.status = 'finished' AND c.game_url IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM game_history g WHERE g.game_url = c.game_url))
)
```

## Mudanças Realizadas

### Arquivo: `tasks.py` (linhas 375-395)
**Antes:**
```python
p1_id, p2_id = (challenger_id, challenged_id)
p1_name = ch.get('challenger_name')
p2_name = ch.get('challenged_name')

if is_swiss_game:
    p1_name = ch.get('player1_name')
    p2_name = ch.get('player2_name')
```

**Depois:**
```python
p1_id, p2_id = (challenger_id, challenged_id)

# Buscar nomes dos jogadores da tabela players
def _get_player_names():
    conn = database.get_conn()
    cur = conn.cursor()
    p1 = cur.execute("SELECT discord_username FROM players WHERE discord_id = ?", (p1_id,)).fetchone()
    p2 = cur.execute("SELECT discord_username FROM players WHERE discord_id = ?", (p2_id,)).fetchone()
    conn.close()
    return p1[0] if p1 else str(p1_id), p2[0] if p2 else str(p2_id)

p1_name, p2_name = await asyncio.to_thread(_get_player_names)

if is_swiss_game:
    p1_name = ch.get('player1_name', p1_name)
    p2_name = ch.get('player2_name', p2_name)
```

### Arquivo: `database.py` (linhas 775-795)
**Antes:**
```python
WHERE c.status = 'accepted' AND c.game_url IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id)
```

**Depois:**
```python
WHERE (
    -- Desafios aceitos que ainda não foram salvos em game_history
    (c.status = 'accepted' AND c.game_url IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.challenge_id = c.id))
    OR
    -- Desafios finalizados que ainda não foram salvos em game_history
    (c.status = 'finished' AND c.game_url IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM game_history g WHERE g.game_url = c.game_url))
)
```

## Resultados

✅ Partidas agora são corretamente salvas em `game_history`
✅ Endpoint `/api/historico/<discord_id>` retorna o histórico de partidas
✅ Nomes dos jogadores são salvos corretamente
✅ Modo de jogo (blitz, rapid, bullet, etc) é registrado
✅ Ratings antes/depois são calculados e salvos

## Como Usar

1. Use o comando `/check_games` para processar manualmente partidas finalizadas
2. Ou acesse o endpoint API: `GET /api/historico/<discord_id>`
