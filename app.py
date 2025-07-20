import os
import time
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import uuid
import logging
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db, auth

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

# Firebase Helpers
def get_user_ref(user_id):
    return db.reference(f'users/{user_id}')

def get_scores_ref():
    return db.reference('scores')

def create_firebase_user():
    """Создает анонимного пользователя в Firebase Auth"""
    try:
        user = auth.create_user()
        return user.uid
    except Exception as e:
        logger.error(f"Ошибка создания пользователя Firebase: {str(e)}")
        return None

@app.route('/api/init', methods=['GET'])
def init_session():
    try:
        user_id = request.cookies.get('user_id')
        
        if not user_id:
            # Создаем нового пользователя в Firebase Auth
            user_id = create_firebase_user()
            if not user_id:
                return jsonify({'error': 'Failed to create user'}), 500
                
            logger.info(f"Новый пользователь: {user_id}")
            
            # Создаем запись в Realtime Database
            user_ref = get_user_ref(user_id)
            user_ref.set({
                'display_name': f'Игрок {str(uuid.uuid4())[:4]}',
                'created_at': {'.sv': 'timestamp'},
                'last_seen_at': {'.sv': 'timestamp'}
            })
            
            response = make_response(jsonify({
                'user_id': user_id,
                'display_name': user_ref.get().get('display_name', 'Игрок')
            }))
            
            response.set_cookie(
                'user_id',
                user_id,
                max_age=31536000,
                httponly=True,
                samesite='None',
                secure=True,
                path='/'
            )
            return response
        
        # Обновляем время последнего посещения
        get_user_ref(user_id).update({
            'last_seen_at': {'.sv': 'timestamp'}
        })
        
        user_data = get_user_ref(user_id).get()
        
        return jsonify({
            'user_id': user_id,
            'display_name': user_data.get('display_name', 'Игрок')
        })
            
    except Exception as e:
        logger.error(f"Ошибка инициализации: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user', methods=['GET', 'PUT'])
def user_profile():
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
            
        user_ref = get_user_ref(user_id)
        
        if request.method == 'GET':
            user_data = user_ref.get()
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
                
            return jsonify({
                'user_id': user_id,
                'display_name': user_data.get('display_name', 'Игрок')
            })
            
        elif request.method == 'PUT':
            data = request.get_json()
            new_name = data.get('display_name', '').strip()
            
            if len(new_name) < 2:
                return jsonify({'error': 'Имя слишком короткое'}), 400
            if len(new_name) > 20:
                return jsonify({'error': 'Имя слишком длинное'}), 400
            
            user_ref.update({
                'display_name': new_name
            })
            
            return jsonify({
                'user_id': user_id,
                'display_name': new_name
            })
                
    except Exception as e:
        logger.error(f"Ошибка работы с профилем: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/scores', methods=['GET', 'POST'])
def handle_scores():
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
            
        if request.method == 'POST':
            data = request.get_json()
            score = data.get('score')
            
            if not isinstance(score, int) or score < 0:
                return jsonify({'error': 'Некорректный счет'}), 400
            
            # Получаем данные пользователя
            user_data = get_user_ref(user_id).get()
            if not user_data:
                return jsonify({'error': 'User not found'}), 404
            
            # Сохраняем результат
            new_score_ref = get_scores_ref().push()
            new_score_ref.set({
                'user_id': user_id,
                'display_name': user_data.get('display_name', 'Игрок'),
                'score': score,
                'date': {'.sv': 'timestamp'}
            })
            
            return jsonify({'status': 'success'})
            
        elif request.method == 'GET':
            # Получаем топ-100 результатов
            scores = get_scores_ref().order_by_child('score').limit_to_last(100).get()
            if not scores:
                return jsonify([])
                
            # Преобразуем в список и сортируем по убыванию
            scores_list = [{'id': k, **v} for k, v in scores.items()]
            sorted_scores = sorted(scores_list, key=lambda x: -x['score'])
            
            # Форматируем дату
            for score in sorted_scores:
                if 'date' in score:
                    score['date'] = time.strftime('%Y-%m-%d %H:%M', 
                                                time.localtime(score['date']/1000))
            
            return jsonify(sorted_scores[:50])  # Возвращаем топ-50
                
    except Exception as e:
        logger.error(f"Ошибка работы с рекордами: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        # Проверка соединения с Firebase
        db.reference('healthcheck').set({'status': 'ok', 'timestamp': {'.sv': 'timestamp'}})
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', False))
