# elo_calculator.py

def calculate_elo(winner_rating: int, loser_rating: int, k_factor: int = 32):
    """
    Calcula os novos ratings para o vencedor e o perdedor usando o sistema Elo.
    """
    # Transforma os ratings em pontuações de expectativa
    expected_winner = 1 / (1 + 10 ** ((loser_rating - winner_rating) / 400))
    expected_loser = 1 / (1 + 10 ** ((winner_rating - loser_rating) / 400))

    # Calcula os novos ratings
    new_winner_rating = round(winner_rating + k_factor * (1 - expected_winner))
    new_loser_rating = round(loser_rating + k_factor * (0 - expected_loser))

    return new_winner_rating, new_loser_rating

def calculate_elo_draw(player1_rating: int, player2_rating: int, k_factor: int = 32):
    """
    Calcula os novos ratings para dois jogadores em caso de empate usando o sistema Elo.
    """
    # Transforma os ratings em pontuações de expectativa
    expected_player1 = 1 / (1 + 10 ** ((player2_rating - player1_rating) / 400))
    expected_player2 = 1 / (1 + 10 ** ((player1_rating - player2_rating) / 400))

    # Calcula os novos ratings (empate = 0.5 pontos)
    new_player1_rating = round(player1_rating + k_factor * (0.5 - expected_player1))
    new_player2_rating = round(player2_rating + k_factor * (0.5 - expected_player2))

    return new_player1_rating, new_player2_rating
