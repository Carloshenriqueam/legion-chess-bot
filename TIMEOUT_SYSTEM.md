# Sistema de Gerenciamento de Torneios Suíços - Timeout e Abandono

## Visão Geral

Este sistema implementa um mecanismo robusto para lidar com jogadores inativos ou que abandonam torneios suíços, garantindo que o torneio continue fluindo mesmo com participantes problemáticos.

## Funcionalidades Implementadas

### 1. Timeouts Automáticos

#### Timeout de Aceitação (1 minuto)
- **Quando**: Jogadores têm 1 minuto para aceitar um pareamento
- **Ação**: Se nenhum jogador aceitar dentro do prazo, ambos recebem derrota
- **Penalidade**: Jogadores que não aceitaram são penalizados
- **Redistribuição**: Novos pareamentos são criados para jogadores restantes

#### Timeout de Finalização (1 hora)
- **Quando**: Após aceitar, jogadores têm 1 hora para finalizar a partida
- **Ação**: Sistema consulta API do Lichess para determinar resultado
- **Cenários**:
  - Partida terminou: Processa resultado normalmente
  - Partida em andamento: Vitória para jogador com último movimento
  - Partida não começou: Ambos recebem derrota

### 2. Abandono Automático

#### Detecção de Inatividade
- **Critério**: Jogador inativo por 2 rodadas consecutivas
- **Ação**: Jogador é automaticamente removido do torneio
- **Consequências**:
  - Todas as partidas restantes consideradas derrotas
  - Banimento de 7 dias para novos torneios

#### Abandono Voluntário
- **Comando**: `/abandonar_torneio <tournament_id>`
- **Botão**: "Abandonar Torneio" nas mensagens de pareamento
- **Confirmação**: Interface com botões para confirmar/cancelar
- **Penalidades**: Mesmo que abandono automático

### 3. Redistribuição de Pareamentos

#### Quando Ocorre
- Após timeouts de aceitação
- Após abandono de jogadores
- Quando pareamentos ficam inválidos

#### Lógica
- Identifica jogadores sem pareamento válido
- Cria novos pareamentos entre jogadores disponíveis
- Concede byes se necessário (número ímpar de jogadores)

## Constantes de Configuração

```python
TIMEOUT_ACCEPT_MINUTES = 1     # Tempo para aceitar partida
TIMEOUT_FINISH_HOURS = 1       # Tempo para finalizar partida
MAX_INACTIVE_ROUNDS = 2        # Máximo de rodadas inativas
ABANDON_PENALTY_DAYS = 7       # Dias de banimento por abandono
```

## Componentes Técnicos

### Classes Modificadas

#### `AcceptSwissGameView`
- Rastreia quem aceitou o pareamento (`accepted_by`)
- Agenda verificações de timeout automáticas
- Processa timeouts de aceitação e finalização
- Inclui botão de abandono voluntário do torneio

### Funções Auxiliares

#### `handle_pairing_timeout(bot, tournament_id, pairing_id, round_number)`
- Processa penalidades para jogadores que não aceitaram
- Notifica jogadores sobre derrotas por timeout

#### `handle_game_finish_timeout(bot, tournament_id, pairing_id, round_number)`
- Consulta API do Lichess para resultado
- Determina vencedor baseado no estado da partida

#### `check_player_abandonment(bot, tournament_id)`
- Verifica inatividade de todos os participantes
- Remove jogadores com muitas rodadas inativas

#### `redistribute_pairings(tournament_id, round_number)`
- Recria pareamentos após problemas
- Garante que todos os jogadores ativos tenham oponentes

### Comando Slash e Botões

#### `/abandonar_torneio` e Botão "Abandonar Torneio"
- Permite abandono voluntário com confirmação
- Comando slash ou botão nas mensagens de pareamento
- Aplica todas as penalidades automaticamente

## Fluxo de Funcionamento

1. **Pareamento Criado**: View com botões é enviada aos jogadores
2. **Aceitação**: Jogadores clicam "Aceitar Partida" dentro de 1 minuto
3. **Criação do Jogo**: Quando ambos aceitam, desafio é criado no Lichess
4. **Timeout de Aceitação**: Se não aceitaram, penalidades aplicadas
5. **Jogo em Andamento**: Jogadores jogam no Lichess
6. **Timeout de Finalização**: Após 1 hora, resultado determinado automaticamente
7. **Abandono**: Jogadores inativos são removidos automaticamente
8. **Redistribuição**: Novos pareamentos criados conforme necessário

## Benefícios

- **Continuidade**: Torneios nunca ficam parados por jogadores inativos
- **Justiça**: Penalidades consistentes e automáticas
- **Transparência**: Jogadores recebem notificações claras
- **Robustez**: Sistema lida com diversos cenários de falha

## Testes

Um script de teste (`test_timeout_system.py`) foi criado para validar:
- Criação de torneios e pareamentos
- Processamento de timeouts
- Verificação de abandono
- Redistribuição de pareamentos

## 🔧 **Correções de Segurança Implementadas**

### ✅ **1. Correção de Bugs Críticos**
- **Timeout Arguments**: Corrigidos argumentos incorretos em `redistribute_pairings()` 
- **Validação de Estado**: Verificação obrigatória se torneio ainda está ativo em todos callbacks
- **Locks para Race Conditions**: Implementados locks assíncronos para criação de jogos e processamento de resultados

### ✅ **2. Rate Limiting**
- **Sistema Global**: Cache de timestamps por usuário/ação
- **Limite**: 1 ação por minuto por tipo (aceitar, finalizar, abandonar)
- **Proteção**: Previne spam e ataques de flood

### ✅ **3. Validação de Usuários Lichess**
- **Registro Obrigatório**: Username Lichess deve estar registrado antes de participar
- **Mapeamento Seguro**: Validação rigorosa de usernames nos resultados
- **Prevenção de Fraudes**: Verificação se username corresponde ao jogador esperado

### ✅ **4. Prevenção de Processamento Duplicado**
- **Locks de Resultados**: Impede processamento simultâneo de resultados
- **Double-Check**: Verificações redundantes dentro dos locks
- **Estado Atômico**: Transações seguras para atualizações críticas

## Considerações Técnicas

- **Assíncrono**: Todas as operações usam asyncio para não bloquear
- **Thread-Safe**: Consultas ao banco são protegidas
- **Error Handling**: Exceções são logadas e não quebram o fluxo
- **Performance**: Verificações são eficientes e não sobrecarregam o sistema