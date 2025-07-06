from flask import Flask, request, jsonify, make_response
import sqlite3
from datetime import datetime
from flask_cors import CORS
import os
import uuid
import logging

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')  # Для production используйте настоящий секретный ключ

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки CORS с поддержкой credentials
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://ваш-фронтенд.домен", "http://localhost:*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True,
        "expose_headers": ["Set-Cookie"]
    }
})

# Конфигурация базы данных
DATABASE = os.path.join(os.getcwd(), 'persistent_storage.db')

def get_db_connection():
    try:
        os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.error(f"Ошибка подключения к БД: {str(e)}")
        raise

def init_db():
    logger.info(f"Инициализация базы данных в {DATABASE}...")
    try:
        with get_db_connection() as db:
            db.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    created_at TEXT NOT NULL,
                    last_activity TEXT NOT NULL
                )
            ''')
            
            db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            ''')
            
            db.execute('''
                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    date TEXT NOT NULL,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            ''')
            
            db.commit()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {str(e)}")
        raise

# Инициализация БД при старте
with app.app_context():
    if not os.path.exists(DATABASE):
        init_db()

@app.route('/api/healthcheck', methods=['GET'])
def healthcheck():
    return jsonify({
        'status': 'ok',
        'session': bool(request.cookies.get('session_id'))
    })

@app.route('/api/session', methods=['GET', 'POST'])
def handle_session():
    try:
        session_id = request.cookies.get('session_id')
        
        # Если сессия не существует
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"Создана новая сессия: {session_id}")
            
            with get_db_connection() as db:
                # Создаем новую сессию
                db.execute(
                    'INSERT INTO sessions (session_id, created_at, last_activity) VALUES (?, ?, ?)',
                    (session_id, datetime.now().isoformat(), datetime.now().isoformat())
                )
                
                # Создаем нового пользователя
                db.execute(
                    'INSERT INTO users (display_name, created_at) VALUES (?, ?)',
                    (f"Игрок_{session_id[:5]}", datetime.now().isoformat())
                )
                user_id = db.lastrowid
                
                # Связываем пользователя с сессией
                db.execute(
                    'UPDATE sessions SET user_id = ? WHERE session_id = ?',
                    (user_id, session_id)
                )
                db.commit()
        
        # Обновляем активность сессии
        with get_db_connection() as db:
            db.execute(
                'UPDATE sessions SET last_activity = ? WHERE session_id = ?',
                (datetime.now().isoformat(), session_id)
            )
            db.commit()
            
            # Получаем данные пользователя
            user = db.execute(
                'SELECT u.id, u.display_name FROM users u JOIN sessions s ON u.id = s.user_id WHERE s.session_id = ?',
                (session_id,)
            ).fetchone()
            
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
            
            response = make_response(jsonify({
                'user_id': user['id'],
                'display_name': user['display_name']
            }))
            
            # Устанавливаем/обновляем куку
            response.set_cookie(
                'session_id',
                session_id,
                max_age=60*60*24*30,  # 30 дней
                httponly=True,
                samesite='None' if 'RENDER' in os.environ else 'Lax',
                secure=True,
                path='/'
            )
            
            return response
            
    except Exception as e:
        logger.error(f"Ошибка работы с сессией: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user', methods=['GET', 'PUT'])
def handle_user():
    try:
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        if request.method == 'GET':
            with get_db_connection() as db:
                user = db.execute(
                    'SELECT u.id, u.display_name FROM users u JOIN sessions s ON u.id = s.user_id WHERE s.session_id = ?',
                    (session_id,)
                ).fetchone()
                
                if not user:
                    return jsonify({'error': 'Пользователь не найден'}), 404
                
                return jsonify(dict(user))
                
        elif request.method == 'PUT':
            data = request.get_json()
            if not data or 'display_name' not in data or len(data['display_name'].strip()) < 2:
                return jsonify({'error': 'Имя должно содержать минимум 2 символа'}), 400
                
            with get_db_connection() as db:
                db.execute(
                    'UPDATE users SET display_name = ? WHERE id = (SELECT user_id FROM sessions WHERE session_id = ?)',
                    (data['display_name'].strip(), session_id)
                )
                db.commit()
                
                user = db.execute(
                    'SELECT u.id, u.display_name FROM users u JOIN sessions s ON u.id = s.user_id WHERE s.session_id = ?',
                    (session_id,)
                ).fetchone()
                
                return jsonify(dict(user))
                
    except Exception as e:
        logger.error(f"Ошибка работы с пользователем: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/scores', methods=['GET', 'POST'])
def handle_scores():
    try:
        session_id = request.cookies.get('session_id')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        with get_db_connection() as db:
            user = db.execute(
                'SELECT user_id FROM sessions WHERE session_id = ?',
                (session_id,)
            ).fetchone()
            
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
                
            user_id = user['user_id']
            
            if request.method == 'POST':
                data = request.get_json()
                if not data or 'score' not in data or not isinstance(data['score'], int):
                    return jsonify({'error': 'Некорректный счёт'}), 400
                    
                db.execute(
                    'INSERT INTO scores (user_id, score, date) VALUES (?, ?, ?)',
                    (user_id, data['score'], datetime.now().isoformat())
                )
                db.commit()
                return jsonify({'status': 'success'})
                
            elif request.method == 'GET':
                scores = db.execute('''
                    SELECT u.display_name as player, s.score, s.date 
                    FROM scores s
                    JOIN users u ON s.user_id = u.id
                    ORDER BY s.score DESC
                    LIMIT 100
                ''').fetchall()
                
                return jsonify([dict(score) for score in scores])
                
    except Exception as e:
        logger.error(f"Ошибка работы с рекордами: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
