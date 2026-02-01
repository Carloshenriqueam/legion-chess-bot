#!/usr/bin/env python3
"""Script para aplicar os fixes do Swiss Tournament"""

import re

def fix_byes_and_standings():
    """Corrige problemas de byes e update_standings"""
    
    with open('database.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    old_code = '''            try:
                for player1_id, player2_id in pairings:
                    cursor.execute(\'\'\'
                        INSERT INTO swiss_pairings (tournament_id, round_number, player1_id, player2_id, status)
                        VALUES (?, ?, ?, ?, 'pending')
                    \'\'\', (tournament_id, round_number, player1_id, player2_id))

                conn.commit()
                return True, pairings
            finally:
                conn.close()'''
    
    new_code = '''            try:
                for player1_id, player2_id in pairings:
                    if player2_id is None:
                        cursor.execute(\'\'\'
                            INSERT INTO swiss_pairings (tournament_id, round_number, player1_id, player2_id, status, winner_id, finished_at)
                            VALUES (?, ?, ?, ?, 'finished', ?, CURRENT_TIMESTAMP)
                        \'\'\', (tournament_id, round_number, player1_id, player2_id, player1_id))
                    else:
                        cursor.execute(\'\'\'
                            INSERT INTO swiss_pairings (tournament_id, round_number, player1_id, player2_id, status)
                            VALUES (?, ?, ?, ?, 'pending')
                        \'\'\', (tournament_id, round_number, player1_id, player2_id))

                conn.commit()
                conn.close()
                
                swiss = SwissTournament(tournament_id)
                swiss.update_standings()
                swiss.close()
                
                return True, pairings
            finally:
                pass'''
    
    if old_code in content:
        content = content.replace(old_code, new_code)
        with open('database.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ database.py foi corrigido!")
        return True
    else:
        print("❌ Padrão não encontrado em database.py")
        return False

def fix_result_logic():
    """Corrige typo nas linhas 177 e 189 do tasks.py"""
    
    with open('tasks.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    old_177 = "challenger_id if winner_id == challenged_id else challenged_id)"
    new_177 = "challenger_id if winner_id == challenged_id else challenger_id)"
    
    count = content.count(old_177)
    
    if count >= 2:
        content = content.replace(old_177, new_177)
        with open('tasks.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"✅ tasks.py foi corrigido! ({count} ocorrências substituídas)")
        return True
    else:
        print(f"⚠️  Apenas {count} ocorrência(ões) encontrada(s) em tasks.py")
        return False

if __name__ == '__main__':
    print("🔧 Aplicando fixes do Swiss Tournament...\n")
    
    success1 = fix_byes_and_standings()
    success2 = fix_result_logic()
    
    if success1 and success2:
        print("\n✅ Todos os fixes foram aplicados com sucesso!")
        print("🚀 Reinicie o bot para as mudanças entrarem em efeito.")
    else:
        print("\n⚠️  Alguns fixes não puderam ser aplicados. Verifique manualmente.")
