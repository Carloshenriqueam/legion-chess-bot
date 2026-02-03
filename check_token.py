# check_token.py
import os

# --- Passo 1: Verifica se existe uma variável de ambiente no sistema ---
system_token = os.environ.get('DISCORD_TOKEN')
if system_token:
    print(f"--- Verificação de Variável de Ambiente do Sistema ---")
    print(f"⚠️  Encontrei uma variável de ambiente DISCORD_TOKEN no seu sistema operacional.")
    print(f"    Valor: {system_token[:5]}...{system_token[-5:]}")
    print(f"    Esta variável pode estar sobrepondo o valor do seu arquivo .env.")
    print("-" * 20)
else:
    print("✅ Nenhuma variável de ambiente DISCORD_TOKEN encontrada no sistema.")

# --- Passo 2: Lê manualmente o arquivo .env ---
print("\n--- Verificação Manual do Arquivo .env ---")
try:
    with open('.env', 'r', encoding='utf-8') as f:
        print("✅ Arquivo .env encontrado e aberto com sucesso.")
        found_in_file = False
        for line in f:
            # Ignora comentários e linhas em branco
            if line.strip() and not line.strip().startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    if key == 'DISCORD_TOKEN':
                        found_in_file = True
                        print(f"🔑 Token encontrado no arquivo .env!")
                        if value:
                            print(f"   Valor: {value[:5]}...{value[-5:]}")
                            if system_token and system_token != value:
                                print("   🚨 ALERTA: O token no arquivo é DIFERENTE do token no ambiente do sistema!")
                        else:
                            print("   ❌ ERRO: A variável DISCORD_TOKEN está vazia no arquivo!")
                        break
        if not found_in_file:
            print("❌ ERRO: A linha `DISCORD_TOKEN=` não foi encontrada no arquivo .env.")

except FileNotFoundError:
    print("❌ ERRO CRÍTICO: O arquivo .env não foi encontrado nesta pasta.")
    print("   Verifique se o nome do arquivo é exatamente `.env` (e não `.env.txt`, por exemplo).")
except Exception as e:
    print(f"❌ Ocorreu um erro inesperado ao ler o arquivo: {e}")

print("\n--- Conclusão ---")
print("Compare o valor do token impresso acima com o novo token que você gerou no Portal do Discord.")
print("Se o valor estiver incorreto ou o arquivo não for encontrado, corrija o arquivo .env.")