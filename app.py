import os
import time
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import uuid
import logging
import psycopg2
from psycopg2 import pool, OperationalError
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

# Пул соединений PostgreSQL
connection_pool = None

def init_db_pool():
    global connection_pool
    max_retries = 3
    retry_delay = 2
    
    for attempt in range(max_retries):
        try:
            connection_pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=5,
                dsn=os.getenv('DATABASE_URL'),
                sslmode='require',
                connect_timeout=3,
                keepalives=1,
                keepalives_idle=30,
                keepalives_interval=10
            )
            logger.info("Пул соединений к PostgreSQL инициализирован")
            return True
        except OperationalError as e:
            logger.error(f"Попытка {attempt + 1}/{max_retries} не удалась: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.critical("Не удалось инициализировать пул соединений")
    return False

def get_db_connection():
    max_retries = 2
    retry_delay = 1
    
    for attempt in range(max_retries):
        try:
            return connection_pool.getconn()
        except OperationalError as e:
            logger.warning(f"Ошибка подключения (попытка {attempt + 1}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    
    raise OperationalError("Не удалось получить соединение из пула")

def init_db_schema():
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            # Создаем таблицы, если их нет
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    session_id VARCHAR(36) UNIQUE NOT NULL,
                    display_name VARCHAR(50) NOT NULL DEFAULT 'Player',
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scores (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id),
                    score INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL DEFAULT NOW()
                )
            """)
            conn.commit()
            logger.info("Схема БД успешно инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации схемы БД: {str(e)}")
        raise
    finally:
        if conn:
            connection_pool.putconn(conn)

# Инициализация при старте
if not init_db_pool():
    exit(1)
init_db_schema()

@app.route('/api/init', methods=['GET'])
def init_session():
    conn = None
    try:
        session_id = request.cookies.get('game_session')
        
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"Создана новая сессия: {session_id}")
            
            conn = get_db_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (session_id)
                    VALUES (%s)
                    ON CONFLICT (session_id) DO NOTHING
                    RETURNING id, display_name
                """, (session_id,))
                
                user = cur.fetchone()
                if not user:
                    cur.execute("SELECT id, display_name FROM users WHERE session_id = %s", (session_id,))
                    user = cur.fetchone()
                
                conn.commit()
                
                response = make_response(jsonify({
                    'user_id': user['id'],
                    'display_name': user['display_name'],
                    'session_id': session_id
                }))
                
                response.set_cookie(
                    'game_session',
                    session_id,
                    max_age=31536000,  # 1 год
                    httponly=True,
                    samesite='None',
                    secure=True,
                    path='/'
                )
                return response
        
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE users 
                SET last_seen_at = NOW()
                WHERE session_id = %s
                RETURNING id, display_name
            """, (session_id,))
            
            user = cur.fetchone()
            conn.commit()
            
            if not user:
                return init_session()
            
            return jsonify({
                'user_id': user['id'],
                'display_name': user['display_name'],
                'session_id': session_id
            })
            
    except Exception as e:
        logger.error(f"Ошибка инициализации сессии: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            connection_pool.putconn(conn)

@app.route('/api/user', methods=['GET', 'PUT'])
def user_profile():
    conn = None
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        conn = get_db_connection()
        with conn.cursor() as cur:
            if request.method == 'GET':
                cur.execute("""
                    SELECT id, display_name 
                    FROM users 
                    WHERE session_id = %s
                """, (session_id,))
                
                user = cur.fetchone()
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                    
                return jsonify({
                    'user_id': user['id'],
                    'display_name': user['display_name']
                })
                
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
                    
                return jsonify({
                    'user_id': user['id'],
                    'display_name': user['display_name']
                })
                
    except Exception as e:
        logger.error(f"Ошибка работы с профилем: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            connection_pool.putconn(conn)

@app.route('/api/scores', methods=['GET', 'POST'])
def handle_scores():
    conn = None
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        conn = get_db_connection()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if request.method == 'POST':
                data = request.get_json()
                score = data.get('score')
                
                if not isinstance(score, int) or score < 0:
                    return jsonify({'error': 'Invalid score'}), 400
                
                cur.execute("SELECT id FROM users WHERE session_id = %s", (session_id,))
                user = cur.fetchone()
                
                if not user:
                    return jsonify({'error': 'User not found'}), 404
                
                cur.execute("""
                    INSERT INTO scores (user_id, score)
                    VALUES (%s, %s)
                """, (user['id'], score))
                conn.commit()
                
                return jsonify({'status': 'success'})
                
            elif request.method == 'GET':
                cur.execute("""
                    SELECT u.display_name, s.score, s.date
                    FROM scores s
                    JOIN users u ON s.user_id = u.id
                    ORDER BY s.score DESC
                    LIMIT 10
                """)
                return jsonify(cur.fetchall())
                
    except Exception as e:
        logger.error(f"Ошибка работы с рекордами: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500
    finally:
        if conn:
            connection_pool.putconn(conn)

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return jsonify({
                'status': 'healthy',
                'database': 'connected',
                'timestamp': datetime.now().isoformat()
            })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
    finally:
        if 'conn' in locals():
            connection_pool.putconn(conn)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
