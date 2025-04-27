import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

# Токен для доступа к API Telegram
BOT_TOKEN = os.getenv('BOT_TOKEN')

# Идентификаторы администраторов (список строк с ID)
ADMINS = [admin_id.strip() for admin_id in os.getenv('ADMINS', '').split(',') if admin_id.strip()]

# Настройки подключения к базе данных
db_path = os.path.join('data', 'history_bot.db')
DB_ENGINE = os.getenv('DB_ENGINE', f'sqlite:///{db_path}')

# Настройки бота
ENABLE_PARENT_REPORTS = os.getenv('ENABLE_PARENT_REPORTS', 'True').lower() == 'true'

# Пути к файлам - используем os.path для корректной работы на всех платформах
DATA_DIR = os.getenv('DATA_DIR', 'data')
MEDIA_DIR = os.path.join(DATA_DIR, 'media')
QUESTIONS_DIR = os.path.join(DATA_DIR, 'questions')

# Убедимся, что все необходимые директории существуют
for directory in [DATA_DIR, MEDIA_DIR, QUESTIONS_DIR, os.path.dirname(db_path)]:
    os.makedirs(directory, exist_ok=True)