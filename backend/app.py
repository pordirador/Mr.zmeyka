from flask import Flask, request, jsonify, make_response
import sqlite3
from datetime import datetime
from flask_cors import CORS
import os
import uuid
import logging

app = Flask(__name__)

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True
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
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
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
            
            # Создаём индекс для быстрого поиска лучших результатов
            db.execute('CREATE INDEX IF NOT EXISTS idx_scores_user_score ON scores(user_id, score)')
            
            db.commit()
        logger.info("База данных успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {str(e)}")
        raise

@app.before_first_request
def before_first_request():
    if not os.path.exists(DATABASE):
        init_db()

@app.route('/api/healthcheck', methods=['GET'])
def healthcheck():
    return jsonify({'status': 'ok', 'database': DATABASE})

@app.route('/api/identify', methods=['GET'])
def identify_user():
    try:
        # Проверяем куки или создаём новую сессию
        session_id = request.cookies.get('snake_game_session')
        
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"Создана новая сессия: {session_id}")
        
        with get_db_connection() as db:
            user = db.execute(
                'SELECT * FROM users WHERE session_id = ?', 
                (session_id,)
            ).fetchone()
            
            if not user:
                # Создаём нового пользователя
                default_name = f"Игрок_{session_id[:5]}"
                db.execute('''
                    INSERT INTO users (session_id, display_name, created_at, last_seen_at)
                    VALUES (?, ?, ?, ?)
                ''', (session_id, default_name, datetime.now().isoformat(), datetime.now().isoformat()))
                db.commit()
                
                user = db.execute(
                    'SELECT * FROM users WHERE session_id = ?', 
                    (session_id,)
                ).fetchone()
                logger.info(f"Создан новый пользователь: {user['id']}")
            
            # Обновляем время последнего посещения
            db.execute(
                'UPDATE users SET last_seen_at = ? WHERE id = ?',
                (datetime.now().isoformat(), user['id'])
            )
            db.commit()
            
            response = make_response(jsonify({
                'id': user['id'],
                'display_name': user['display_name'],
                'session_id': user['session_id']
            }))
            
            # Устанавливаем куку на 30 дней
            response.set_cookie(
                'snake_game_session',
                session_id,
                max_age=60*60*24*30,
                httponly=True,
                samesite='Lax',
                secure=True if 'RENDER' in os.environ else False
            )
            
            return response
            
    except Exception as e:
        logger.error(f"Ошибка идентификации: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user/update', methods=['POST'])
def update_profile():
    try:
        session_id = request.cookies.get('snake_game_session')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        data = request.get_json()
        if not data or 'display_name' not in data or len(data['display_name'].strip()) < 2:
            return jsonify({'error': 'Имя должно содержать минимум 2 символа'}), 400
            
        with get_db_connection() as db:
            # Проверяем существование пользователя
            user = db.execute(
                'SELECT id FROM users WHERE session_id = ?', 
                (session_id,)
            ).fetchone()
            
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
            
            # Обновляем имя
            db.execute('''
                UPDATE users 
                SET display_name = ?
                WHERE session_id = ?
            ''', (data['display_name'].strip(), session_id))
            db.commit()
            
            # Получаем обновлённые данные
            updated_user = db.execute(
                'SELECT * FROM users WHERE session_id = ?', 
                (session_id,)
            ).fetchone()
            
            return jsonify({
                'id': updated_user['id'],
                'display_name': updated_user['display_name'],
                'status': 'updated'
            })
            
    except Exception as e:
        logger.error(f"Ошибка обновления профиля: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/save_score', methods=['POST'])
def save_score():
    try:
        session_id = request.cookies.get('snake_game_session')
        if not session_id:
            return jsonify({'error': 'Сессия не найдена'}), 401
            
        data = request.get_json()
        if not data or 'score' not in data or not isinstance(data['score'], int):
            return jsonify({'error': 'Некорректный счёт'}), 400
            
        with get_db_connection() as db:
            # Получаем пользователя
            user = db.execute(
                'SELECT id FROM users WHERE session_id = ?', 
                (session_id,)
            ).fetchone()
            
            if not user:
                return jsonify({'error': 'Пользователь не найден'}), 404
            
            # Сохраняем результат
            db.execute('''
                INSERT INTO scores (user_id, score, date)
                VALUES (?, ?, ?)
            ''', (user['id'], data['score'], datetime.now().isoformat()))
            db.commit()
            
            return jsonify({'status': 'success', 'saved_score': data['score']})
            
    except Exception as e:
        logger.error(f"Ошибка сохранения счёта: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/get_scores', methods=['GET'])
def get_scores():
    try:
        with get_db_connection() as db:
            # Получаем топ-100 лучших результатов
            scores = db.execute('''
                SELECT u.display_name as player, MAX(s.score) as score, MAX(s.date) as date
                FROM scores s
                JOIN users u ON s.user_id = u.id
                GROUP BY u.id
                ORDER BY score DESC 
                LIMIT 100
            ''').fetchall()
            
            return jsonify([dict(row) for row in scores])
            
    except Exception as e:
        logger.error(f"Ошибка получения рекордов: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
