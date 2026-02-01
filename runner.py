# runner.py
import os
import sys
import subprocess
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# O comando para reiniciar o bot
RESTART_COMMAND = [sys.executable, "main.py"]

def restart_bot():
    print("🔄 Mudança detectada! Reiniciando o bot em 3 segundos...")
    time.sleep(3)
    # Usa subprocess para iniciar um novo processo e sair do atual
    subprocess.Popen(RESTART_COMMAND)
    sys.exit()

class ChangeHandler(FileSystemEventHandler):
    def on_modified(self, event):
        # Verifica se o arquivo modificado é um arquivo Python
        if event.src_path.endswith('.py'):
            print(f"Arquivo modificado: {event.src_path}")
            restart_bot()

if __name__ == "__main__":
    print("🚀 Iniciando o bot com auto-reload...")
    print("💡 Pressione Ctrl+C para parar.")
    
    event_handler = ChangeHandler()
    observer = Observer()
    observer.schedule(event_handler, path='.', recursive=True)
    observer.start()
    
    try:
        # Inicia o processo do bot principal
        subprocess.run(RESTART_COMMAND)
    except KeyboardInterrupt:
        print("🛑 Parando o watcher...")
        observer.stop()
    observer.join()