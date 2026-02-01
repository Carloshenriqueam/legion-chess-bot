# keep_alive.py
from flask import Flask, jsonify
from threading import Thread
import asyncio
import database

app = Flask('')

@app.route('/')
def home():
    return "Legion Chess Bot está online! 🏆"

@app.route('/badge/<discord_id>')
def get_badges(discord_id):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        achievements = loop.run_until_complete(database.get_player_achievements(discord_id))
        loop.close()
        
        if not achievements:
            return jsonify({
                'discord_id': discord_id,
                'achievements': [],
                'total': 0
            })
        
        return jsonify({
            'discord_id': discord_id,
            'achievements': achievements,
            'total': len(achievements)
        })
    except Exception as e:
        return jsonify({
            'error': str(e),
            'discord_id': discord_id
        }), 500

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()