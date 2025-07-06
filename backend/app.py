from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from flask_cors import CORS
import os
import uuid

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Конфигурация базы данных
DATABASE = os.path.join(os.getcwd(), 'database.db')

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
                session_id TEXT UNIQUE NOT NULL,
                display_name TEXT NOT NULL,
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

@app.route('/api/identify', methods=['GET'])
def identify_user():
    try:
        db = get_db_connection()
        
        # Проверяем наличие session_id в куках
        session_id = request.cookies.get('session_id')
        
        if not session_id:
            # Создаем новый session_id
            session_id = str(uuid.uuid4())
        
        user = db.execute(
            'SELECT * FROM users WHERE session_id = ?', 
            (session_id,)
        ).fetchone()
        
        if not user:
            # Создаем нового пользователя
            default_name = f"Игрок_{session_id[:8]}"
            db.execute('''
                INSERT INTO users (session_id, display_name, created_at, last_seen_at)
                VALUES (?, ?, ?, ?)
            ''', (session_id, default_name, datetime.now().isoformat(), datetime.now().isoformat()))
            db.commit()
            
            user = db.execute(
                'SELECT * FROM users WHERE session_id = ?', 
                (session_id,)
            ).fetchone()
        
        # Обновляем время последнего посещения
        db.execute(
            'UPDATE users SET last_seen_at = ? WHERE id = ?',
            (datetime.now().isoformat(), user['id'])
        )
        db.commit()
        
        response = jsonify(dict(user))
        response.set_cookie('session_id', session_id, max_age=60*60*24*30)  # 30 дней
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/user/update', methods=['POST'])
def update_profile():
    try:
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        data = request.get_json()
        if not data or 'display_name' not in data:
            return jsonify({'error': 'Необходимо указать имя'}), 400
            
        db = get_db_connection()
        
        db.execute('''
            UPDATE users 
            SET display_name = ?
            WHERE session_id = ?
        ''', (data['display_name'], session_id))
        
        db.commit()
        
        user = db.execute(
            'SELECT * FROM users WHERE session_id = ?', 
            (session_id,)
        ).fetchone()
        
        return jsonify(dict(user))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

@app.route('/api/save_score', methods=['POST'])
def save_score():
    try:
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        data = request.get_json()
        if not data or 'score' not in data:
            return jsonify({'error': 'Необходимо указать счет'}), 400
            
        db = get_db_connection()
        
        user = db.execute(
            'SELECT id FROM users WHERE session_id = ?', 
            (session_id,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        # Всегда сохраняем новый результат (история рекордов)
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
        # Берем лучший результат каждого пользователя
        scores = db.execute('''
            SELECT u.display_name as player, MAX(s.score) as score, s.date
            FROM scores s
            JOIN users u ON s.user_id = u.id
            GROUP BY u.id
            ORDER BY score DESC 
            LIMIT 100
        ''').fetchall()
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        init_db()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
