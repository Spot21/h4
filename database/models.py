from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

Base = declarative_base()

# Связующая таблица для отношения многие-ко-многим между Question и TestResult
question_result = Table(
    'question_result',
    Base.metadata,
    Column('question_id', Integer, ForeignKey('questions.id')),
    Column('test_result_id', Integer, ForeignKey('test_results.id')),
    Column('is_correct', Boolean, default=False, nullable=False),
    Column('user_answer', String),
)

# Связующая таблица для родитель-ученик
parent_student = Table(
    'parent_student',
    Base.metadata,
    Column('parent_id', Integer, ForeignKey('users.id')),
    Column('student_id', Integer, ForeignKey('users.id')),
)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)  # Это будет telegram username
    full_name = Column(String, nullable=True)  # Это будет введенные Имя и Фамилия
    role = Column(String, nullable=False)  # student, parent, admin
    user_group = Column(String, nullable=True)  # Новое поле для класса ученика
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_active = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    settings = Column(String, nullable=True)  # JSON строка с настройками пользователя

    # Отношения
    results = relationship("TestResult", back_populates="user")
    achievements = relationship("Achievement", back_populates="user")

    # Родительское отношение
    children = relationship(
        "User",
        secondary=parent_student,
        primaryjoin=(id == parent_student.c.parent_id),
        secondaryjoin=(id == parent_student.c.student_id),
        backref="parents"
    )

class BotSettings(Base):
    __tablename__ = 'bot_settings'

    id = Column(Integer, primary_key=True)
    key = Column(String, nullable=False, unique=True)
    value = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

class Topic(Base):
    __tablename__ = 'topics'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)

    # Отношения
    questions = relationship("Question", back_populates="topic")


class Question(Base):
    __tablename__ = 'questions'

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    text = Column(String, nullable=False)
    options = Column(String, nullable=False)  # JSON строка с вариантами ответов
    correct_answer = Column(String, nullable=False)  # JSON строка с правильными ответами
    question_type = Column(String, nullable=False)  # single, multiple
    difficulty = Column(Integer, default=1)  # 1-5
    media_url = Column(String, nullable=True)  # URL или путь к медиа-файлу
    explanation = Column(String, nullable=True)  # Объяснение правильного ответа

    # Отношения
    topic = relationship("Topic", back_populates="questions")
    test_results = relationship("TestResult", secondary=question_result, back_populates="questions")


class TestResult(Base):
    __tablename__ = 'test_results'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    score = Column(Float, nullable=False)
    max_score = Column(Float, nullable=False)
    percentage = Column(Float, nullable=False)
    time_spent = Column(Integer, nullable=True)  # в секундах
    completed_at = Column(DateTime, default=datetime.now(timezone.utc))

    # Отношения
    user = relationship("User", back_populates="results")
    topic = relationship("Topic")
    questions = relationship("Question", secondary=question_result, back_populates="test_results")


class Achievement(Base):
    __tablename__ = 'achievements'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    achieved_at = Column(DateTime, default=datetime.now(timezone.utc))
    badge_url = Column(String, nullable=True)
    points = Column(Integer, default=0)

    # Отношения
    user = relationship("User", back_populates="achievements")


class Notification(Base):
    __tablename__ = 'notifications'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    scheduled_at = Column(DateTime, nullable=True)
    notification_type = Column(String, nullable=False)  # reminder, report, achievement

    # Отношения
    user = relationship("User")
