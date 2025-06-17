from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_name TEXT,
            score INTEGER,
            date TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Сохранение результата
@app.route('/api/save_score', methods=['POST'])
def save_score():
    data = request.json
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO scores (player_name, score, date)
        VALUES (?, ?, ?)
    ''', (data.get('player_name'), data['score'], datetime.now().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# Получение топ-10 результатов
@app.route('/api/get_scores', methods=['GET'])
def get_scores():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT player_name, score FROM scores ORDER BY score DESC LIMIT 10')
    scores = cursor.fetchall()
    conn.close()
    return jsonify([{"player": row[0], "score": row[1]} for row in scores])

if __name__ == '__main__':
    app.run(debug=True)
