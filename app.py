import os
from flask import Flask, request, jsonify, make_response
from datetime import datetime
from flask_cors import CORS
import uuid
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки CORS
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://pordirador.github.io", "http://localhost:*"],
        "methods": ["GET", "POST", "PUT", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True,
        "expose_headers": ["Set-Cookie"]
    }
})

# Подключение к PostgreSQL
def get_db():
    # Используйте DATABASE_URL от Render (он создаётся автоматически)
    database_url = os.getenv('DATABASE_URL')
    
    if not database_url:
        raise ValueError("DATABASE_URL не задан в переменных окружения")
    
    # Подключение с правильными параметрами
    return psycopg2.connect(
        dsn=database_url,
        sslmode='require'  # Обязательно для Render
    )

# Инициализация БД
def init_db():
    try:
        with get_db() as conn, conn.cursor() as cur:
            # Проверка существования таблиц
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM pg_tables 
                    WHERE schemaname = 'public' 
                    AND tablename = 'users'
                )
            """)
            if not cur.fetchone()[0]:
                cur.execute("""
                    CREATE TABLE users (
                        id SERIAL PRIMARY KEY,
                        session_id VARCHAR(36) UNIQUE NOT NULL,
                        display_name VARCHAR(50) NOT NULL DEFAULT 'Player',
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        last_seen_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """)
                # ... остальные таблицы
                conn.commit()
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")
        raise
@app.route('/api/init', methods=['GET'])

def init_session():
    """Инициализация сессии и пользователя"""
    try:
        session_id = request.cookies.get('game_session')
        
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"Создана новая сессия: {session_id}")
            
            with get_db() as conn, conn.cursor() as cur:
                # Создаем нового пользователя
                cur.execute("""
                    INSERT INTO users (session_id)
                    VALUES (%s)
                    RETURNING id, display_name
                """, (session_id,))
                
                user = cur.fetchone()
                conn.commit()
                
                response = make_response(jsonify({
                    'user_id': user['id'],
                    'display_name': user['display_name'],
                    'session_id': session_id
                }))
                
                # Устанавливаем куку на 1 год
                response.set_cookie(
    'game_session',
    session_id,
    max_age=31536000,
    httponly=True,
    samesite='None',
    secure=True,
    path='/',
    domain='.render.com'  # Добавьте это
)
                
                return response
        
        # Обновляем существующую сессию
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE users 
                SET last_seen_at = NOW()
                WHERE session_id = %s
                RETURNING id, display_name
            """, (session_id,))
            
            user = cur.fetchone()
            conn.commit()
            
            if not user:
                # Если сессия есть, но пользователь не найден - создаем нового
                return init_session()
            
            return jsonify({
                'user_id': user['id'],
                'display_name': user['display_name'],
                'session_id': session_id
            })
            
    except Exception as e:
        logger.error(f"Ошибка инициализации сессии: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user', methods=['GET', 'PUT'])
def user_profile():
    """Работа с профилем пользователя"""
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        with get_db() as conn, conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute("""
                    SELECT id, display_name 
                    FROM users 
                    WHERE session_id = %s
                """, (session_id,))
                
                user = cur.fetchone()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                    
                return jsonify(dict(user))
                
            elif request.method == 'PUT':
                data = request.get_json()
                new_name = data.get('display_name', '').strip()
                
                if len(new_name) < 2:
                    return jsonify({'error': 'Name too short'}), 400
                
                cur.execute("""
                    UPDATE users
                    SET display_name = %s
                    WHERE session_id = %s
                    RETURNING id, display_name
                """, (new_name, session_id))
                
                user = cur.fetchone()
                conn.commit()
                
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                    
                return jsonify(dict(user))
                
    except Exception as e:
        logger.error(f"Ошибка работы с профилем: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/scores', methods=['GET', 'POST'])
def handle_scores():
    """Работа с рекордами"""
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        with get_db() as conn, conn.cursor() as cur:
            if request.method == 'POST':
                data = request.get_json()
                score = data.get('score')
                
                if not isinstance(score, int) or score < 0:
                    return jsonify({'error': 'Invalid score'}), 400
                
                # Получаем user_id
                cur.execute("""
                    SELECT id FROM users WHERE session_id = %s
                """, (session_id,))
                user = cur.fetchone()
                
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                
                # Сохраняем результат
                cur.execute("""
                    INSERT INTO scores (user_id, score)
                    VALUES (%s, %s)
                """, (user['id'], score))
                conn.commit()
                
                return jsonify({'status': 'success'})
                
            elif request.method == 'GET':
                # Топ-100 результатов
                cur.execute("""
                    SELECT u.display_name, s.score, s.date
                    FROM scores s
                    JOIN users u ON s.user_id = u.id
                    ORDER BY s.score DESC
                    LIMIT 100
                """)
                
                scores = cur.fetchall()
                return jsonify([dict(row) for row in scores])
                
    except Exception as e:
        logger.error(f"Ошибка работы с рекордами: {e}")
        return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
