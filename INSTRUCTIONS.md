# Instructions for Stockfish Integration

To use the new game analysis feature, you need to install a few things:

1.  **Install the Stockfish engine:**
    -   Download the Stockfish engine for your operating system from the official website: https://stockfishchess.org/download/
    -   Extract the downloaded file and place the `stockfish` executable in a known location on your system.

2.  **Install the `stockfish` Python library:**
    -   Open your terminal or command prompt.
    -   Activate the virtual environment if you are using one: `venv\Scripts\activate`
    -   Run the following command: `pip install stockfish`

3.  **Configure the Stockfish path:**
    -   In the `.env` file, add the following line, replacing `"path/to/your/stockfish.exe"` with the actual path to the Stockfish executable you downloaded in step 1:
        ```
        STOCKFISH_PATH="path/to/your/stockfish.exe"
        ```
