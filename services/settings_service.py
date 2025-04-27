import logging
from database.models import BotSettings
from database.db_manager import get_session

logger = logging.getLogger(__name__)


def get_setting(key: str, default=None):
    """Получение настройки по ключу"""
    try:
        with get_session() as session:
            setting = session.query(BotSettings).filter(BotSettings.key == key).first()
            if setting:
                return setting.value
            return default
    except Exception as e:
        logger.error(f"Ошибка при получении настройки {key}: {e}")
        return default


def set_setting(key: str, value):
    """Установка настройки"""
    try:
        with get_session() as session:
            setting = session.query(BotSettings).filter(BotSettings.key == key).first()
            if setting:
                setting.value = str(value)
            else:
                setting = BotSettings(key=key, value=str(value))
                session.add(setting)
            session.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при установке настройки {key}: {e}")
        return False


def get_quiz_settings():
    """Получение настроек теста"""
    questions_count = int(get_setting("default_questions_count", "10"))

    # Определение времени в зависимости от количества вопросов
    if questions_count <= 10:
        time_limit = 5 * 60  # 5 минут в секундах
    elif questions_count <= 15:
        time_limit = 10 * 60  # 10 минут в секундах
    else:
        time_limit = 20 * 60  # 20 минут в секундах

    return {
        "questions_count": questions_count,
        "time_limit": time_limit,
        "time_minutes": time_limit // 60
    }