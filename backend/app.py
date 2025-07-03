from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любого домена

# Конфигурация базы данных
DATABASE = 'database.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        db = get_db_connection()
        db.execute('''
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_name TEXT NOT NULL,
                score INTEGER NOT NULL,
                date TEXT NOT NULL
            )
        ''')
        db.commit()
        db.close()

@app.route('/api/save_score', methods=['POST'])
def save_score():
    data = request.get_json()
    
    if not data or 'player_name' not in data or 'score' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    try:
        db = get_db_connection()
        db.execute('''
            INSERT INTO scores (player_name, score, date)
            VALUES (?, ?, ?)
        ''', (data['player_name'], data['score'], datetime.now().isoformat()))
        db.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/get_scores', methods=['GET'])
def get_scores():
    try:
        db = get_db_connection()
        scores = db.execute('''
            SELECT player_name as player, score 
            FROM scores 
            ORDER BY score DESC 
            LIMIT 10
        ''').fetchall()
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Для Render нужно указать порт 10000
@app.route('/')
def home():
    return jsonify({
        "status": "API is working",
        "endpoints": {
            "save_score": "/api/save_score (POST)",
            "get_scores": "/api/get_scores (GET)"
        }
    })
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=10000)  # Render использует порт 10000
