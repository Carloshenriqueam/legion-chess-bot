#!/usr/bin/env python3
import os
from dotenv import load_dotenv
import stockfish_analysis

load_dotenv()
stockfish_path = os.getenv('STOCKFISH_PATH')
if not stockfish_path:
    print('STOCKFISH_PATH not set')
    raise SystemExit(1)

pgn = '''[Event "Casual"]
[White "A"]
[Black "B"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 Na5 9. Bc2 c5 10. d3 O-O 1-0
'''

analysis = stockfish_analysis.GameAnalysis(pgn, stockfish_path, depth=10)
print('Running analysis...')
result = analysis.analyze_game()
print(f'Moves analyzed: {len(result)}')

# classification logic from cogs

def classify_move(eval_change, is_best):
    if eval_change is None:
        return 'Mate'
    if is_best:
        return 'Melhor'
    elif eval_change <= 0:
        return 'Excelente'
    elif eval_change <= 15:
        return 'Bom'
    elif eval_change <= 50:
        return 'Imprecisão'
    elif eval_change <= 200:
        return 'Erro'
    else:
        return 'Blunder'

for m in result:
    cls = classify_move(m.get('eval_change'), m.get('is_best'))
    print(f"PLY {m['ply']:2d} {m['move']:6s} eval_change={m.get('eval_change')} is_mate={m.get('is_mate')} class={cls}")

# compute simple stats excluding mate
moves_no_mate = [m for m in result if not m.get('is_mate')]
print(f"Moves (excluding mate): {len(moves_no_mate)}")

big_errors = sorted([m for m in moves_no_mate if m.get('eval_change') and m.get('eval_change')>50], key=lambda x: x['eval_change'], reverse=True)[:5]
print('Top mistakes:')
for m in big_errors:
    print(f" PLY {m['ply']:2d} {m['move']:6s} loss={m['eval_change']}")
