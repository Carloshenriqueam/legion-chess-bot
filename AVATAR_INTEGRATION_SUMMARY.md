# Sumário da Integração de Avatares - Legionchess-New

## ✅ O Que Foi Feito

### 1. **Corrigido o Banco de Dados**
   - ✅ Adicionada coluna `avatar_hash` à tabela `players`
   - ✅ Arquivo: [database.py](database.py#L137)
   - Campo agora captura o hash do avatar do Discord

### 2. **Sincronizados os Avatares**
   - ✅ Executado `sync_avatars.py` com sucesso
   - ✅ **2 jogadores atualizados** com seus avatares
   - ✅ `avatar_hash` salvos no banco de dados

**Exemplo de dados sincronizados:**
```
carloshenri: 70da9fe56bbb84efa611f9afe494df55
carloshenriam3: 4ccb92ab1d00491ae6648f758eb294ae
```

### 3. **Criada Função de API**
   - ✅ Adicionada `get_ranking_by_mode_for_api()` em [database.py](database.py#L2603)
   - ✅ Retorna dados formatados com `id_discord`, `avatar_hash`, ratings, etc.
   - ✅ Pronta para ser chamada pelo backend do site novo

### 4. **Documentação Criada**
   - ✅ [AVATAR_INTEGRATION.md](AVATAR_INTEGRATION.md) - Guia completo
   - ✅ [BACKEND_PATCH_LEGIONCHESS_NEW.md](BACKEND_PATCH_LEGIONCHESS_NEW.md) - Patch para app.py

---

## 🔧 Próximos Passos (Para Você Fazer)

### No Arquivo: `C:\Users\carlu\Desktop\legionchess-new\backend\app.py`

Adicione este endpoint:

```python
@app.route('/api/ranking/<mode>', methods=['GET'])
async def get_ranking(mode):
    """Retorna ranking com avatares dos jogadores"""
    try:
        if mode not in ['bullet', 'blitz', 'rapid', 'classic']:
            return jsonify({'error': 'Modo inválido'}), 400
        
        # Importar função do bot
        import sys
        sys.path.insert(0, r'C:\Users\carlu\legion-chess-bot')
        from database import get_ranking_by_mode_for_api
        
        ranking_data = await get_ranking_by_mode_for_api(mode)
        return jsonify(ranking_data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
```

### Teste

```bash
# No PowerShell, em qualquer diretório
curl http://localhost:5000/api/ranking/blitz
```

Deve retornar:
```json
{
  "jogadores": [
    {
      "id_discord": "123456789",
      "nome": "carloshenri",
      "avatar_hash": "70da9fe56bbb84efa611f9afe494df55",
      "rating": 1200,
      "vitorias": 0,
      "derrotas": 0,
      "empates": 0,
      "partidas_jogadas": 0
    }
  ],
  "ultimo_update": "2026-01-23T..."
}
```

---

## 📊 Fluxo de Dados

```
Discord (avatares)
    ↓
sync_avatars.py (busca e sincroniza)
    ↓
legion_chess.db (armazena avatar_hash)
    ↓
database.get_ranking_by_mode_for_api() (lê e formata)
    ↓
legionchess-new/backend/app.py (expõe via API)
    ↓
Frontend (legionchess-new) (monta URL e exibe)
    ↓
https://cdn.discordapp.com/avatars/{id}/{hash}.png (imagem aparece)
```

---

## 🎯 Como Funciona No Frontend

O site React recebe e processa:

```typescript
// Recebe do backend
const data = {
  jogadores: [{
    id_discord: "123456789",
    avatar_hash: "70da9fe56bbb84efa611f9afe494df55",
    ...
  }]
}

// Processa
const avatarUrl = `https://cdn.discordapp.com/avatars/123456789/70da9fe56bbb84efa611f9afe494df55.png`;

// Exibe na tag img
<img src={avatarUrl} alt="Player Avatar" />
```

---

## 🔄 Sincronização Automática (Opcional)

Para sincronizar avatares automaticamente quando o bot inicia:

Adicione ao `main.py`:

```python
# Na função on_ready()
await sync_avatars()  # Chama o script de sincronização
```

---

## 📝 Resumo das Alterações

| Arquivo | Alteração | Status |
|---------|-----------|--------|
| database.py | Adicionada coluna `avatar_hash` | ✅ |
| database.py | Adicionada função `get_ranking_by_mode_for_api()` | ✅ |
| sync_avatars.py | Executado com sucesso | ✅ |
| legion_chess.db | Avatares sincronizados | ✅ |
| app.py (novo site) | **PENDENTE** - Adicionar endpoint | ⏳ |

---

## ⚠️ Troubleshooting

### Erro: "ModuleNotFoundError: No module named 'database'"
**Solução:** Adicione ao app.py:
```python
import sys
sys.path.insert(0, r'C:\Users\carlu\legion-chess-bot')
```

### Erro: "avatar_hash is NULL"
**Solução:** Execute novamente:
```bash
C:\Users\carlu\legion-chess-bot\venv\Scripts\python.exe sync_avatars.py
```

### Imagens não carregam no site
1. Verifique se a URL está sendo construída corretamente
2. Teste a URL diretamente: `https://cdn.discordapp.com/avatars/123456789/hash.png`
3. Verifique o console do navegador para erros CORS

---

## 📚 Referências

- **Discord API**: https://discord.com/developers/docs/resources/user#avatar-data
- **CDN de Avatares**: https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png
- **Formato Avatar Hash**: String hexadecimal de 32 caracteres

---

## ✨ Resultado Final

Após implementar o endpoint no backend, o site será capaz de:
1. ✅ Buscar avatares do banco de dados
2. ✅ Construir URLs do Discord CDN
3. ✅ Exibir fotos dos jogadores no ranking
4. ✅ Funcionar sem necessidade de proxy

