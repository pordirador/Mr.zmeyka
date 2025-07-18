import os
import time
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import uuid
import logging
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Инициализация Firebase
cred = credentials.Certificate("firebase-service-account.json")  # Ваш сервисный аккаунт
firebase_admin.initialize_app(cred, {
    'databaseURL': os.getenv('FIREBASE_DB_URL')
})

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки CORS (остаются без изменений)
CORS(app, resources={
    r"/api/*": {
        "origins": ["https://pordirador.github.io", "http://localhost:*"],
        "methods": ["GET", "POST", "PUT", "OPTIONS"],
        "allow_headers": ["Content-Type"],
        "supports_credentials": True,
        "expose_headers": ["Set-Cookie"]
    }
})

# Firebase Helpers
def get_user_ref(session_id):
    return db.reference(f'users/{session_id}')

def get_scores_ref():
    return db.reference('scores')

@app.route('/api/init', methods=['GET'])
def init_session():
    try:
        session_id = request.cookies.get('game_session')
        
        if not session_id:
            session_id = str(uuid.uuid4())
            logger.info(f"Новая сессия: {session_id}")
            
            # Создаем нового пользователя в Firebase
            user_ref = get_user_ref(session_id)
            user_ref.set({
                'display_name': 'Player',
                'created_at': {'.sv': 'timestamp'},
                'last_seen_at': {'.sv': 'timestamp'}
            })
            
            response = make_response(jsonify({
                'user_id': session_id,
                'display_name': 'Player',
                'session_id': session_id
            }))
            
            response.set_cookie(
                'game_session',
                session_id,
                max_age=31536000,
                httponly=True,
                samesite='None',
                secure=True,
                path='/'
            )
            return response
        
        # Обновляем время последнего посещения
        get_user_ref(session_id).update({
            'last_seen_at': {'.sv': 'timestamp'}
        })
        
        user_data = get_user_ref(session_id).get()
        
        return jsonify({
            'user_id': session_id,
            'display_name': user_data.get('display_name', 'Player'),
            'session_id': session_id
        })
            
    except Exception as e:
        logger.error(f"Ошибка сессии: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user', methods=['GET', 'PUT'])
def user_profile():
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        user_ref = get_user_ref(session_id)
        
        if request.method == 'GET':
            user_data = user_ref.get()
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
                
            return jsonify({
                'user_id': session_id,
                'display_name': user_data.get('display_name', 'Player')
            })
            
        elif request.method == 'PUT':
            data = request.get_json()
            new_name = data.get('display_name', '').strip()
            
            if len(new_name) < 2:
                return jsonify({'error': 'Name too short'}), 400
            
            user_ref.update({
                'display_name': new_name
            })
            
            return jsonify({
                'user_id': session_id,
                'display_name': new_name
            })
                
    except Exception as e:
        logger.error(f"Ошибка работы с профилем: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/scores', methods=['GET', 'POST'])
def handle_scores():
    try:
        session_id = request.cookies.get('game_session')
        if not session_id:
            return jsonify({'error': 'Session not found'}), 401
            
        if request.method == 'POST':
            data = request.get_json()
            score = data.get('score')
            
            if not isinstance(score, int) or score < 0:
                return jsonify({'error': 'Invalid score'}), 400
            
            # Получаем данные пользователя
            user_data = get_user_ref(session_id).get()
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
            
            # Сохраняем результат
            new_score_ref = get_scores_ref().push()
            new_score_ref.set({
                'user_id': session_id,
                'display_name': user_data.get('display_name', 'Player'),
                'score': score,
                'date': {'.sv': 'timestamp'}
            })
            
            return jsonify({'status': 'success'})
            
        elif request.method == 'GET':
            # Получаем топ-10 результатов
            scores = get_scores_ref().order_by_child('score').limit_to_last(10).get()
            if not scores:
                return jsonify([])
                
            # Сортируем по убыванию score
            sorted_scores = sorted(scores.values(), key=lambda x: -x['score'])
            return jsonify(sorted_scores)
                
    except Exception as e:
        logger.error(f"Ошибка работы с рекордами: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Простая проверка доступности Firebase
        db.reference('healthcheck').set({'status': 'ok'})
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': {'.sv': 'timestamp'}
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
