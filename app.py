import os
import time
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
import uuid
import logging
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, db, auth
import json

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Безопасная инициализация Firebase
def initialize_firebase():
    try:
        # Вариант 1: Используем переменные окружения
        if all(k in os.environ for k in ['FIREBASE_TYPE', 'FIREBASE_PROJECT_ID', 
                                       'FIREBASE_PRIVATE_KEY', 'FIREBASE_CLIENT_EMAIL']):
            
            firebase_credentials = {
                "type": os.environ['FIREBASE_TYPE'],
                "project_id": os.environ['FIREBASE_PROJECT_ID'],
                "private_key": os.environ['FIREBASE_PRIVATE_KEY'].replace('\\n', '\n'),
                "client_email": os.environ['FIREBASE_CLIENT_EMAIL'],
                "token_uri": os.environ.get('FIREBASE_TOKEN_URI', "https://oauth2.googleapis.com/token")
            }
            
            cred = credentials.Certificate(firebase_credentials)
            return firebase_admin.initialize_app(cred, {
                'databaseURL': os.getenv('FIREBASE_DB_URL')
            })
        
        # Вариант 2: Используем файл из переменной окружения (для Docker)
        elif 'FIREBASE_CREDENTIALS_JSON' in os.environ:
            cred = credentials.Certificate(json.loads(os.environ['FIREBASE_CREDENTIALS_JSON']))
            return firebase_admin.initialize_app(cred, {
                'databaseURL': os.getenv('FIREBASE_DB_URL')
            })
        
        else:
            raise RuntimeError("Не настроены учетные данные Firebase")
    
    except Exception as e:
        logging.error(f"Ошибка инициализации Firebase: {str(e)}")
        raise

# Инициализация Firebase
try:
    firebase_app = initialize_firebase()
except Exception as e:
    logging.error(f"Не удалось инициализировать Firebase: {str(e)}")
    firebase_app = None

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

def get_user_ref(user_id):
    if not firebase_app:
        raise RuntimeError("Firebase не инициализирован")
    return db.reference(f'users/{user_id}')

def get_scores_ref():
    if not firebase_app:
        raise RuntimeError("Firebase не инициализирован")
    return db.reference('scores')

@app.route('/api/init', methods=['GET'])
def init_session():
    try:
        if not firebase_app:
            return jsonify({'error': 'Сервис временно недоступен'}), 503
            
        user_id = request.cookies.get('user_id')
        
        if not user_id:
            try:
                user = auth.create_user()
                user_id = user.uid
                
                get_user_ref(user_id).set({
                    'display_name': f'Игрок_{str(uuid.uuid4())[:4]}',
                    'created_at': {'.sv': 'timestamp'},
                    'last_seen_at': {'.sv': 'timestamp'}
                })
                
                response = make_response(jsonify({
                    'user_id': user_id,
                    'display_name': f'Игрок_{str(uuid.uuid4())[:4]}'
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
                
            except Exception as e:
                logger.error(f"Ошибка создания пользователя: {str(e)}")
                return jsonify({'error': 'Не удалось создать пользователя'}), 500
        
        try:
            auth.get_user(user_id)
            get_user_ref(user_id).update({
                'last_seen_at': {'.sv': 'timestamp'}
            })
            
            user_data = get_user_ref(user_id).get()
            return jsonify({
                'user_id': user_id,
                'display_name': user_data.get('display_name', f'Игрок_{str(uuid.uuid4())[:4]}')
            })
            
        except auth.UserNotFoundError:
            return jsonify({'error': 'Сессия устарела'}), 401
            
    except Exception as e:
        logger.error(f"Ошибка инициализации: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/user', methods=['PUT'])
def update_profile():
    try:
        if not firebase_app:
            return jsonify({'error': 'Сервис временно недоступен'}), 503
            
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'error': 'Требуется авторизация'}), 401
            
        data = request.get_json()
        new_name = data.get('display_name', '').strip()
        
        if len(new_name) < 2:
            return jsonify({'error': 'Имя должно содержать минимум 2 символа'}), 400
        if len(new_name) > 20:
            return jsonify({'error': 'Имя должно быть не длиннее 20 символов'}), 400
        
        get_user_ref(user_id).update({
            'display_name': new_name,
            'last_seen_at': {'.sv': 'timestamp'}
        })
        
        return jsonify({
            'user_id': user_id,
            'display_name': new_name
        })
        
    except Exception as e:
        logger.error(f"Ошибка обновления профиля: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/scores', methods=['POST'])
def save_score():
    try:
        if not firebase_app:
            return jsonify({'error': 'Сервис временно недоступен'}), 503
            
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'error': 'Требуется авторизация'}), 401
            
        data = request.get_json()
        score = data.get('score')
        
        if not isinstance(score, int) or score < 0:
            return jsonify({'error': 'Некорректный счет'}), 400
            
        user_data = get_user_ref(user_id).get()
        if not user_data:
            return jsonify({'error': 'Пользователь не найден'}), 404
            
        get_scores_ref().push().set({
            'user_id': user_id,
            'display_name': user_data.get('display_name', 'Игрок'),
            'score': score,
            'date': {'.sv': 'timestamp'}
        })
        
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Ошибка сохранения счета: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/scores', methods=['GET'])
def get_leaderboard():
    try:
        if not firebase_app:
            return jsonify({'error': 'Сервис временно недоступен'}), 503
            
        limit = min(int(request.args.get('limit', 10)), 100)
        
        scores = get_scores_ref()\
            .order_by_child('score')\
            .limit_to_last(limit)\
            .get()
            
        if not scores:
            return jsonify([])
            
        sorted_scores = sorted(
            [{'id': k, **v} for k, v in scores.items()],
            key=lambda x: -x['score']
        )
        
        return jsonify(sorted_scores)
        
    except Exception as e:
        logger.error(f"Ошибка получения таблицы лидеров: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    try:
        if not firebase_app:
            return jsonify({'status': 'unhealthy', 'error': 'Firebase not initialized'}), 503
            
        db.reference('healthcheck').set({
            'status': 'ok',
            'timestamp': {'.sv': 'timestamp'}
        })
        
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
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('DEBUG', 'False').lower() == 'true')

@app.route('/api/inventory', methods=['PUT'])
def update_inventory():
    try:
        user_id = request.cookies.get('user_id')
        if not user_id:
            return jsonify({'error': 'Требуется авторизация'}), 401
            
        data = request.get_json()
        if not all(k in data for k in ['type', 'item_id']):
            return jsonify({'error': 'Неверные данные'}), 400
            
        ref = db.reference(f'userSettings/{user_id}/unlockedItems/{data["type"]}')
        current_items = ref.get() or []
        
        if data['item_id'] not in current_items:
            current_items.append(data['item_id'])
            ref.set(current_items)
            
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"Ошибка обновления инвентаря: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500
