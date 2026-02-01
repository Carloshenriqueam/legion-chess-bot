# Sistema de Torneio Swiss do Bot

## Overview

Implementado um **sistema completo de torneios Swiss** gerenciado pelo bot, sem dependência da API do Lichess para criar torneios. O bot agora pode:

1. Criar torneios Swiss locais
2. Gerenciar inscrições de jogadores
3. Gerar pairings automaticamente usando algoritmo Swiss
4. Criar desafios Lichess para os pairings
5. Acompanhar resultados e rankings

## Arquitetura

### Banco de Dados (database.py)

Três novas tabelas:

- **swiss_tournaments**: Armazena informações dos torneios
  - ID, nome, descrição, time_control, número de rodadas
  - Status (open, in_progress, finished)
  - Rodada atual, rated, rating mín/máx

- **swiss_participants**: Jogadores inscritos
  - ID do torneio, ID do jogador
  - Pontuação (points) e Tiebreak score
  
- **swiss_pairings**: Pairings de cada rodada
  - Rodada, dois jogadores, vencedor
  - Status (pending, in_progress, finished, bye)
  - Challenge ID do Lichess

### Algoritmo Swiss (swiss_tournament.py)

Classe `SwissTournament` que gerencia toda a lógica:

- **Primeira rodada**: Pareamento simples alternado
- **Rodadas seguintes**: Pareamento por pontuação
  - Jogadores agrupados por pontos
  - Evita rematches (rematch prevention)
  - Calcula tiebreak (Buchholz/Sum of Opposition Scores)

### Comandos Discord (cogs/tournaments.py)

#### Criar Torneio
```
/criar_swiss nome:"Nome do Torneio" numero_rodadas:5 tempo_inicial:10 incremento:0
```

Parâmetros:
- `nome`: Nome do torneio (obrigatório)
- `descricao`: Descrição (opcional)
- `tempo_inicial`: Minutos (padrão: 10)
- `incremento`: Segundos (padrão: 0)
- `numero_rodadas`: 3-20 (padrão: 5)
- `rated`: Sim/Não (padrão: Sim)
- `rating_minimo`, `rating_maximo`: Restrições de rating

#### Inscrição
```
/entrar_swiss tournament_id:1
```

Adiciona o jogador ao torneio se ainda estiver aberto.

#### Ver Participantes
```
/swiss_participantes tournament_id:1
```

#### Ver Pairings
```
/swiss_pairings tournament_id:1 rodada:1
```

Mostra os pairings da rodada especificada.

#### Ver Rankings
```
/swiss_standings tournament_id:1
```

Mostra o ranking atual com pontos e tiebreak.

#### Iniciar Torneio
```
/iniciar_swiss tournament_id:1
```

Inicia o torneio e gera os pairings da primeira rodada automaticamente. Apenas o criador pode fazer isso.

#### Criar Desafios Lichess
```
/criar_desafios_swiss tournament_id:1 rodada:1
```

Cria desafios Lichess para os pairings de uma rodada. Requer que os jogadores tenham username Lichess registrado.

## Fluxo de Uso

1. **Criador cria o torneio**: `/criar_swiss "Torneio April" numero_rodadas:5`
   - Bot retorna ID do torneio (ex: 1)

2. **Jogadores se inscrevem**: `/entrar_swiss tournament_id:1`
   - Todos entram durante a fase "open"

3. **Criador inicia**: `/iniciar_swiss tournament_id:1`
   - Bot gera primeiro pairing automaticamente
   - Status muda para "in_progress"

4. **Criador cria desafios**: `/criar_desafios_swiss tournament_id:1`
   - Bot cria um desafio aberto no Lichess para cada pairing
   - Jogadores têm tempo para jogar

5. **Acompanhar resultados**: `/swiss_standings tournament_id:1`
   - Ver ranking atualizado

6. **Quando rodada termina**: `/iniciar_swiss tournament_id:1` novamente
   - Bot gera os pairings da próxima rodada
   - Repete processo até final

## Características Principais

### Pareamento Inteligente
- ✅ Primeira rodada: Pareamento simples
- ✅ Próximas rodadas: Agrupa por pontuação
- ✅ Previne rematches
- ✅ Calcula tiebreak automático

### Gerenciamento de Byes
- ✅ Jogadores sem adversário recebem BYE (1 ponto)
- ✅ Bye aparece nos pairings com indicador especial

### Integração Lichess
- ✅ Cria desafios abertos automaticamente
- ✅ Suporta todos os time controls
- ✅ Rated ou unrated

### Flexibilidade
- ✅ Múltiplos torneios simultâneos
- ✅ Restrições de rating
- ✅ Rodadas configuráveis (3-20)
- ✅ Rated e unrated

## Exemplo Prático

```
Usuário: /criar_swiss "Blitz Championship" numero_rodadas:4 tempo_inicial:5 incremento:0 rated:true

Bot: Torneio criado! ID: 42

Usuários: /entrar_swiss tournament_id:42 (5 vezes)

Criador: /iniciar_swiss tournament_id:42
Bot: Torneio iniciado com 5 participantes!
     Rodada 1 pairings:
     1. user1 vs user2
     2. user3 vs user4
     3. user5 (BYE)

Criador: /criar_desafios_swiss tournament_id:42
Bot: 2 desafios criados com sucesso

(Jogadores fazem suas partidas no Lichess)

Admin: /swiss_standings tournament_id:42
Bot mostra:
  1. user1 - 2pts (TB: 2.5)
  2. user5 - 1.5pts (TB: 2.0)
  3. user2 - 1pt (TB: 1.5)
  (etc)
```

## Notas Importantes

1. **Usernames Lichess**: Jogadores precisam ter username Lichess registrado para criar desafios
2. **Algoritmo**: Implementado Swiss modificado - grupo por pontos sem algoritmo de matching matemático complexo
3. **Automático**: Primeira rodada é gerada automaticamente ao iniciar
4. **Manual**: Rodadas subsequentes precisam ser iniciadas manualmente pelo criador

## Futuras Melhorias

- [ ] Algoritmo de pareamento mais sofisticado (Howell movements)
- [ ] Geração automática de desafios integrada ao iniciar rodada
- [ ] Web dashboard com standings em tempo real
- [ ] Export de resultados em PGN
- [ ] Integração com rating Lichess automático
- [ ] Suporte a knockout rounds após Swiss
