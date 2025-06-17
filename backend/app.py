from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from flask_cors import CORS  # Для обработки CORS-запросов

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любого домена (для разработки)

# Инициализация базы данных
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT NOT NULL,
            score INTEGER NOT NULL,
            date TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# Подключение к базе данных
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

# API для сохранения результата
@app.route('/api/save_score', methods=['POST'])
def save_score():
    data = request.get_json()
    
    if not data or 'player_name' not in data or 'score' not in data:
        return jsonify({'error': 'Invalid data'}), 400
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO scores (player_name, score, date)
            VALUES (?, ?, ?)
        ''', (data['player_name'], data['score'], datetime.now().isoformat()))
        conn.commit()
        return jsonify({'status': 'success', 'id': cursor.lastrowid})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# API для получения топ-10 результатов
@app.route('/api/get_scores', methods=['GET'])
def get_scores():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT player_name, score 
            FROM scores 
            ORDER BY score DESC 
            LIMIT 10
        ''')
        scores = cursor.fetchall()
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# Запуск сервера
if __name__ == '__main__':
    init_db()  # Создаем таблицу при первом запуске
    app.run(debug=True, host='0.0.0.0', port=5000)
