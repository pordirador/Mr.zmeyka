from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from flask_cors import CORS
import hashlib
import os

app = Flask(__name__)
CORS(app)

# Конфигурация базы данных
DATABASE = '/tmp/database.db' if 'RENDER' in os.environ else 'database.db'

def get_db_connection():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    if not os.path.exists(DATABASE):
        init_db()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    print(f"Инициализация базы данных в {DATABASE}...")
    try:
        db = sqlite3.connect(DATABASE)
        cursor = db.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip_address TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
                avatar_url TEXT,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                date TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        db.commit()
        print("База данных успешно инициализирована")
    except Exception as e:
        print(f"Ошибка инициализации БД: {str(e)}")
        raise
    finally:
        if db:
            db.close()

def get_client_ip():
    if request.headers.getlist("X-Forwarded-For"):
        return request.headers.getlist("X-Forwarded-For")[0]
    return request.remote_addr

@app.route('/api/identify', methods=['GET'])
def identify_user():
    try:
        ip_address = get_client_ip()
        db = get_db_connection()
        
        user = db.execute(
            'SELECT * FROM users WHERE ip_address = ?', 
            (ip_address,)
        ).fetchone()
        
        if not user:
            # Создаем нового пользователя
            default_name = f"Игрок_{ip_address.replace('.', '_')}"
            db.execute('''
                INSERT INTO users (ip_address, display_name, created_at, last_seen_at)
                VALUES (?, ?, ?, ?)
            ''', (ip_address, default_name, datetime.now().isoformat(), datetime.now().isoformat()))
            db.commit()
            
            user = db.execute(
                'SELECT * FROM users WHERE ip_address = ?', 
                (ip_address,)
            ).fetchone()
        
        # Обновляем время последнего посещения
        db.execute(
            'UPDATE users SET last_seen_at = ? WHERE id = ?',
            (datetime.now().isoformat(), user['id'])
        )
        db.commit()
        
        return jsonify(dict(user))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/user/update', methods=['POST'])
def update_profile():
    try:
        ip_address = get_client_ip()
        data = request.get_json()
        
        if not data or 'display_name' not in data:
            return jsonify({'error': 'Необходимо указать имя'}), 400
            
        db = get_db_connection()
        
        db.execute('''
            UPDATE users 
            SET display_name = ?, avatar_url = ?
            WHERE ip_address = ?
        ''', (data['display_name'], data.get('avatar_url'), ip_address))
        
        db.commit()
        
        user = db.execute(
            'SELECT * FROM users WHERE ip_address = ?', 
            (ip_address,)
        ).fetchone()
        
        return jsonify(dict(user))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/save_score', methods=['POST'])
def save_score():
    try:
        ip_address = get_client_ip()
        data = request.get_json()
        
        if not data or 'score' not in data:
            return jsonify({'error': 'Необходимо указать счет'}), 400
            
        db = get_db_connection()
        
        user = db.execute(
            'SELECT id FROM users WHERE ip_address = ?', 
            (ip_address,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        db.execute('''
            INSERT INTO scores (user_id, score, date)
            VALUES (?, ?, ?)
        ''', (user['id'], data['score'], datetime.now().isoformat()))
        
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
            SELECT u.display_name as player, s.score, s.date
            FROM scores s
            JOIN users u ON s.user_id = u.id
            ORDER BY s.score DESC 
            LIMIT 100
        ''').fetchall()
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/my_scores', methods=['GET'])
def get_my_scores():
    try:
        ip_address = get_client_ip()
        db = get_db_connection()
        
        user = db.execute(
            'SELECT id FROM users WHERE ip_address = ?', 
            (ip_address,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        scores = db.execute('''
            SELECT score, date
            FROM scores
            WHERE user_id = ?
            ORDER BY score DESC
            LIMIT 10
        ''', (user['id'],)).fetchall()
        
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
