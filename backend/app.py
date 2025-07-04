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
DATABASE = 'database.db'

def get_db_connection():
    # Проверяем, нужно ли инициализировать базу данных
    if not os.path.exists(DATABASE):
        init_db()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    print("Инициализация базы данных...")
    with app.app_context():
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
        db.close()
    print("База данных успешно инициализирована")

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

# ... (остальные функции остаются без изменений)

if __name__ == '__main__':
    # Убедимся, что база данных инициализирована перед запуском
    if not os.path.exists(DATABASE):
        init_db()
    app.run(host='0.0.0.0', port=10000, debug=True)
