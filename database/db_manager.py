import logging
import os
import traceback
from contextlib import contextmanager
from typing import Optional
from sqlalchemy import create_engine, event, exc
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.exc import SQLAlchemyError

from config import DB_ENGINE, DATA_DIR, ADMINS
from database.models import Base

logger = logging.getLogger(__name__)

# Проверяем тип базы данных (SQLite или PostgreSQL)
is_sqlite = DB_ENGINE.startswith('sqlite:///')
is_postgres = DB_ENGINE.startswith('postgresql://')

# Создаем движок базы данных с улучшенными настройками
if is_sqlite:
    sqlite_path = DB_ENGINE.replace('sqlite:///', '')
    os.makedirs(os.path.dirname(os.path.abspath(sqlite_path)), exist_ok=True)

    engine = create_engine(
        DB_ENGINE,
        connect_args={"check_same_thread": False},
        echo=False,
        pool_pre_ping=True  # Проверка доступности соединения
    )
else:
    engine = create_engine(
        DB_ENGINE,
        echo=False,
        pool_size=20,  # Увеличиваем размер пула
        max_overflow=30,  # Увеличиваем overflow
        pool_timeout=30,  # Тайм-аут получения соединения
        pool_recycle=3600,  # Пересоздание соединений каждый час
        pool_pre_ping=True,  # Проверка соединения перед использованием
        connect_args={  # Дополнительные параметры для PostgreSQL
            "connect_timeout": 10,
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5
        }
    )

# Создаем фабрику сессий с автоматическим expire_on_commit=False для работы с объектами после коммита
Session = scoped_session(sessionmaker(
    bind=engine,
    autoflush=True,
    autocommit=False,
    expire_on_commit=False  # Важно! Позволяет использовать объекты после закрытия сессии
))


# Настройка обработчиков событий для улучшения стабильности
@event.listens_for(engine, "connect")
def connect(dbapi_connection, connection_record):
    """Обработчик события подключения к БД"""
    connection_record.info['pid'] = os.getpid()


@event.listens_for(engine, "checkout")
def checkout(dbapi_connection, connection_record, connection_proxy):
    """Проверка соединения при получении из пула"""
    pid = os.getpid()
    if connection_record.info['pid'] != pid:
        # Соединение было создано в другом процессе, закрываем его
        connection_record.connection = connection_proxy.connection = None
        raise exc.DisconnectionError(
            "Connection record belongs to pid %s, attempting to check out in pid %s" %
            (connection_record.info['pid'], pid)
        )


def init_db():
    """Инициализация базы данных с улучшенной обработкой ошибок"""
    try:
        # Проверяем подключение
        logger.info(f"Подключение к базе данных: {DB_ENGINE}")
        with engine.connect() as conn:
            logger.info("Соединение с базой данных установлено успешно")



        # Создаем все таблицы
        Base.metadata.create_all(engine)
        logger.info("Таблицы в базе данных созданы успешно")

        # Проверяем наличие данных и добавляем начальные данные при необходимости
        with get_session() as session:
            from database.models import User
            user_count = session.query(User).count()
            logger.info(f"Количество пользователей в базе: {user_count}")

            if user_count == 0:
                add_default_data(session)
                logger.info("Начальные данные добавлены успешно")
            else:
                logger.info("База данных уже содержит данные")

    except Exception as e:
        logger.error(f"Ошибка инициализации базы данных: {e}")
        logger.error(traceback.format_exc())
        raise


@contextmanager
def get_session():
    """Улучшенный контекстный менеджер для работы с сессией"""
    session = Session()
    try:
        yield session
        session.commit()
        logger.debug("Сессия успешно закрыта с commit")
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Ошибка SQLAlchemy: {e}")
        logger.error(traceback.format_exc())
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Неожиданная ошибка в сессии: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        session.close()
        Session.remove()  # Важно! Удаляем сессию из scoped_session


def add_default_data(session=None):
    """Добавление начальных данных в базу данных"""
    should_close_session = False

    try:
        if session is None:
            session = Session()
            should_close_session = True

        from database.models import User, Topic

        # Проверяем, есть ли уже администратор
        admin_exists = session.query(User).filter(User.role == "admin").first() is not None

        if not admin_exists and ADMINS:
            try:
                admin_id = int(ADMINS[0])
                admin = User(
                    telegram_id=admin_id,
                    username="admin",
                    full_name="Admin",
                    role="admin"
                )
                session.add(admin)
                logger.info(f"Default admin user added with ID: {admin_id}")
            except (ValueError, IndexError) as e:
                logger.error(f"Error adding default admin: {e}")

        # Проверяем, есть ли уже темы
        topics_exist = session.query(Topic).first() is not None

        if not topics_exist:
            # Добавляем начальные темы
            topics = [
                Topic(name="Древняя Русь IX-XII вв.",
                      description="Вопросы по истории Древней Руси в период IX-XII веков"),
                # Добавьте другие темы по необходимости
            ]

            session.add_all(topics)
            logger.info("Default topics added")

        if not should_close_session:
            session.flush()  # Flush вместо commit, если сессия будет закрыта внешним контекстом
        else:
            session.commit()

        logger.info("Default data added successfully")

    except Exception as e:
        if should_close_session:
            session.rollback()
        logger.error(f"Error adding default data: {e}")
        logger.error(traceback.format_exc())
        raise
    finally:
        if should_close_session:
            session.close()


# Функция для проверки состояния соединения
def check_connection() -> bool:
    """Проверка соединения с базой данных"""
    try:
        with engine.connect() as conn:
            if is_postgres:
                conn.execute("SELECT 1")
            else:
                conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Ошибка проверки соединения с БД: {e}")
        return False


# Функция для восстановления соединения
def reconnect() -> bool:
    """Попытка восстановления соединения с БД"""
    try:
        logger.info("Попытка восстановления соединения с БД...")
        engine.dispose()
        if check_connection():
            logger.info("Соединение с БД восстановлено успешно")
            return True
        return False
    except Exception as e:
        logger.error(f"Ошибка восстановления соединения с БД: {e}")
        return False