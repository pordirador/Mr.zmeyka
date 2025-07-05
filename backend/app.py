from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime
from flask_cors import CORS
import hashlib
import secrets
import os

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с любого домена

# Конфигурация базы данных
DATABASE = '/tmp/database.db' if 'RENDER' in os.environ else 'database.db'

def get_db_connection():
    # Создаем папку если её нет (для Render)
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    
    # Проверяем и инициализируем БД при первом подключении
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
        
        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                email TEXT UNIQUE,
                token TEXT UNIQUE,
                created_at TEXT NOT NULL
            )
        ''')
        
        # Таблица рекордов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                date TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        
        # Таблица профилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                avatar_url TEXT,
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

# Хеширование пароля
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Генерация токена
def generate_token():
    return secrets.token_hex(32)

# Регистрация пользователя
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Необходимо указать имя пользователя и пароль'}), 400
    
    try:
        db = get_db_connection()
        
        # Проверка существования пользователя
        existing_user = db.execute(
            'SELECT id FROM users WHERE username = ?', 
            (data['username'],)
        ).fetchone()
        
        if existing_user:
            return jsonify({'error': 'Имя пользователя уже занято'}), 400
        
        # Создание пользователя
        password_hash = hash_password(data['password'])
        token = generate_token()
        
        db.execute('''
            INSERT INTO users (username, password_hash, token, created_at)
            VALUES (?, ?, ?, ?)
        ''', (data['username'], password_hash, token, datetime.now().isoformat()))
        
        user_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        
        # Создание профиля
        db.execute('''
            INSERT INTO profiles (user_id, display_name)
            VALUES (?, ?)
        ''', (user_id, data['username']))
        
        db.commit()
        return jsonify({'token': token, 'user_id': user_id})
        
    except sqlite3.Error as e:
        return jsonify({'error': f'Ошибка базы данных: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Авторизация пользователя
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    
    if not data or 'username' not in data or 'password' not in data:
        return jsonify({'error': 'Необходимо указать имя пользователя и пароль'}), 400
    
    try:
        db = get_db_connection()
        
        user = db.execute(
            'SELECT id, password_hash FROM users WHERE username = ?', 
            (data['username'],)
        ).fetchone()
        
        if not user or user['password_hash'] != hash_password(data['password']):
            return jsonify({'error': 'Неверное имя пользователя или пароль'}), 401
        
        # Обновление токена
        token = generate_token()
        db.execute(
            'UPDATE users SET token = ? WHERE id = ?',
            (token, user['id'])
        )
        db.commit()
        
        return jsonify({'token': token, 'user_id': user['id']})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Получение информации о пользователе
@app.route('/api/user', methods=['GET'])
def get_user():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    try:
        db = get_db_connection()
        
        user = db.execute('''
            SELECT u.id, u.username, p.display_name, p.avatar_url
            FROM users u
            LEFT JOIN profiles p ON u.id = p.user_id
            WHERE u.token = ?
        ''', (token,)).fetchone()
        
        if not user:
            return jsonify({'error': 'Неверный токен'}), 401
            
        return jsonify(dict(user))
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Обновление профиля
@app.route('/api/user/update', methods=['POST'])
def update_profile():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    data = request.get_json()
    
    try:
        db = get_db_connection()
        
        # Проверяем токен
        user = db.execute(
            'SELECT id FROM users WHERE token = ?', 
            (token,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Неверный токен'}), 401
        
        # Обновляем профиль
        db.execute('''
            UPDATE profiles
            SET display_name = ?, avatar_url = ?
            WHERE user_id = ?
        ''', (data.get('display_name'), data.get('avatar_url'), user['id']))
        
        db.commit()
        return jsonify({'status': 'success'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Сохранение результата игры
@app.route('/api/save_score', methods=['POST'])
def save_score():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    data = request.get_json()
    
    try:
        db = get_db_connection()
        
        # Проверяем токен
        user = db.execute(
            'SELECT id FROM users WHERE token = ?', 
            (token,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Неверный токен'}), 401
        
        # Сохраняем результат
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

# Получение таблицы лидеров
@app.route('/api/get_scores', methods=['GET'])
def get_scores():
    try:
        db = get_db_connection()
        scores = db.execute('''
            SELECT p.display_name as player, s.score, s.date
            FROM scores s
            JOIN profiles p ON s.user_id = p.user_id
            ORDER BY s.score DESC 
            LIMIT 100
        ''').fetchall()
        return jsonify([dict(row) for row in scores])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()

# Получение личных рекордов
@app.route('/api/my_scores', methods=['GET'])
def get_my_scores():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'error': 'Требуется авторизация'}), 401
    
    try:
        db = get_db_connection()
        
        user = db.execute(
            'SELECT id FROM users WHERE token = ?', 
            (token,)
        ).fetchone()
        
        if not user:
            return jsonify({'error': 'Неверный токен'}), 401
        
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
    # Убедимся, что база данных инициализирована перед запуском
    if not os.path.exists(DATABASE):
        init_db()
    
    # Для Render нужно указать порт из переменной окружения
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=True)
