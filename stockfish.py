import subprocess
import time
import re

class Stockfish:
    def __init__(self, path="stockfish"):
        self.path = path
        self.process = subprocess.Popen(
            path,
            universal_newlines=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._set_option("UCI_AnalyseMode", "true")
        self._set_option("Contempt", 0) # No contempt for analysis
        self._set_option("Threads", 4)
        self._set_option("Hash", 256)
        self._put("uci")
        self._wait_for_ready()

    def _set_option(self, name, value):
        self._put(f"setoption name {name} value {value}")

    def _put(self, command):
        if self.process.stdin:
            self.process.stdin.write(f"{command}\n")
            self.process.stdin.flush()

    def _wait_for_ready(self):
        self._put("isready")
        while True:
            line = self.process.stdout.readline().strip()
            if line == "readyok":
                break

    def set_fen_position(self, fen_string):
        self._put(f"position fen {fen_string}")

    def get_evaluation(self, time_ms=3000):
        self._put(f"go movetime {time_ms}")
        return self._read_evaluation_output()

    def _read_evaluation_output(self):
        last_eval = {"type": "cp", "value": 0}
        best_move = None
        start_time = time.time()
        timeout = 25  # 25 second timeout per move
        
        while time.time() - start_time < timeout:
            try:
                line = self.process.stdout.readline(1024).strip()
                if not line:
                    # If empty line received but no bestmove yet, continue waiting
                    time.sleep(0.01)
                    continue

                # Look for 'info depth X score cp Y' or 'info depth X score mate Z'
                match_cp = re.search(r"score cp (-?\d+)", line)
                match_mate = re.search(r"score mate (-?\d+)", line)
                match_bestmove = re.search(r"bestmove (\S+)", line)

                if match_cp:
                    last_eval = {"type": "cp", "value": int(match_cp.group(1))}
                elif match_mate:
                    last_eval = {"type": "mate", "value": int(match_mate.group(1))}
                
                if match_bestmove:
                    best_move = match_bestmove.group(1)
                    break  # Stop when bestmove is found

            except Exception as e:
                time.sleep(0.01)
                continue

        return {"evaluation": last_eval, "best_move": best_move}

    def __del__(self):
        if self.process:
            self.process.kill()
