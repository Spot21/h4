import json
import random
import os
import logging
import traceback
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Question, TestResult, User, Topic, Achievement
from database.db_manager import get_session
from services.cache_service import CacheService
from services.notification import NotificationService
from services.stats_service import update_user_stats
from utils.formatters import format_question_text
from utils.image_utils import get_image_path

logger = logging.getLogger(__name__)

class QuizService:
    def __init__(self):
        self.active_quizzes = {}
        self._auto_save_task = None
        self._save_lock = asyncio.Lock()  # Блокировка для безопасного сохранения
        self.cache = CacheService()  # Добавляем кеш

    async def start(self):
        """Запуск сервиса"""
        await self.cache.start()
        await self.start_auto_save()

    async def stop(self):
        """Остановка сервиса"""
        await self.stop_auto_save()
        await self.cache.stop()

    async def start_auto_save(self):
        """Запуск автоматического сохранения состояния"""
        if self._auto_save_task is None:
            self._auto_save_task = asyncio.create_task(self._auto_save_loop())
            logger.info("Auto-save task started")

    async def stop_auto_save(self):
        """Остановка автоматического сохранения"""
        if self._auto_save_task:
            self._auto_save_task.cancel()
            try:
                await self._auto_save_task
            except asyncio.CancelledError:
                pass
            self._auto_save_task = None
            logger.info("Auto-save task stopped")

    async def _auto_save_loop(self):
        """Цикл автоматического сохранения каждые 30 секунд"""
        while True:
            try:
                await asyncio.sleep(30)
                await self.save_active_quizzes_async()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in auto-save loop: {e}")

    async def save_active_quizzes_async(self):
        """Асинхронное сохранение состояния активных тестов"""
        async with self._save_lock:
            await asyncio.to_thread(self.save_active_quizzes)

    def save_active_quizzes(self):
        """Улучшенное сохранение состояния активных тестов"""
        try:
            # Создаем директорию, если она не существует
            save_dir = os.path.join('data', 'quiz_state')
            os.makedirs(save_dir, exist_ok=True)

            # Создаем временный файл для атомарного сохранения
            temp_file = os.path.join(save_dir, '.temp_state.json')

            # Сохраняем общее состояние
            state_data = {
                'version': '1.0',
                'saved_at': datetime.now(timezone.utc).isoformat(),
                'active_count': len(self.active_quizzes)
            }

            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(state_data, f, ensure_ascii=False, indent=2)

            # Переименовываем во избежание потери данных
            final_file = os.path.join(save_dir, 'state.json')
            os.replace(temp_file, final_file)

            # Сохраняем каждый активный тест
            saved_count = 0
            for user_id, quiz_data in self.active_quizzes.items():
                try:
                    # Подготавливаем данные для сохранения
                    save_data = self._prepare_quiz_data_for_save(quiz_data)

                    # Сохраняем в отдельный файл
                    user_temp_file = os.path.join(save_dir, f'.temp_user_{user_id}.json')
                    with open(user_temp_file, 'w', encoding='utf-8') as f:
                        json.dump(save_data, f, ensure_ascii=False, indent=2)

                    # Атомарное переименование
                    user_final_file = os.path.join(save_dir, f'user_{user_id}.json')
                    os.replace(user_temp_file, user_final_file)
                    saved_count += 1

                except Exception as e:
                    logger.error(f"Error saving quiz for user {user_id}: {e}")
                    # Удаляем временный файл если он существует
                    if os.path.exists(user_temp_file):
                        try:
                            os.remove(user_temp_file)
                        except:
                            pass

            # Удаляем старые файлы для неактивных пользователей
            self._cleanup_old_quiz_files(save_dir)

            logger.info(f"Saved {saved_count}/{len(self.active_quizzes)} active quizzes")

        except Exception as e:
            logger.error(f"Error saving active quizzes: {e}")
            logger.error(traceback.format_exc())

    def _prepare_quiz_data_for_save(self, quiz_data: Dict[str, Any]) -> Dict[str, Any]:
        """Подготовка данных теста для сохранения"""
        # Создаем копию для безопасности
        save_data = quiz_data.copy()

        # Конвертируем datetime объекты
        if 'start_time' in save_data and isinstance(save_data['start_time'], datetime):
            save_data['start_time'] = save_data['start_time'].isoformat()

        if 'end_time' in save_data and isinstance(save_data['end_time'], datetime):
            save_data['end_time'] = save_data['end_time'].isoformat()

        # Добавляем метаданные
        save_data['_saved_at'] = datetime.now(timezone.utc).isoformat()
        save_data['_version'] = '1.0'

        return save_data

    def _json_serializer(self, obj):
        """Помощник для сериализации объектов в JSON"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    def get_notification_service(self) -> Optional['NotificationService']:
        """Получение сервиса уведомлений с проверкой"""
        service = getattr(self, 'notification_service', None)
        if service is None:
            logger.warning("NotificationService не инициализирован в QuizService")
        return service

    def restore_active_quizzes(self):
        """Улучшенное восстановление активных тестов из файлов"""
        try:
            save_dir = os.path.join('data', 'quiz_state')
            if not os.path.exists(save_dir):
                logger.info("No saved quiz state directory found")
                return

            # Читаем общее состояние
            state_file = os.path.join(save_dir, 'state.json')
            if os.path.exists(state_file):
                try:
                    with open(state_file, 'r', encoding='utf-8') as f:
                        state_data = json.load(f)

                    saved_at = datetime.fromisoformat(state_data['saved_at'])
                    age_minutes = (datetime.now(timezone.utc) - saved_at).total_seconds() / 60

                    logger.info(f"Found saved state from {age_minutes:.1f} minutes ago")

                except Exception as e:
                    logger.error(f"Error reading state file: {e}")

            # Загружаем каждый сохраненный тест
            restored_count = 0
            expired_count = 0

            for filename in os.listdir(save_dir):
                if filename.startswith('user_') and filename.endswith('.json'):
                    try:
                        user_id = int(filename.replace('user_', '').replace('.json', ''))
                        file_path = os.path.join(save_dir, filename)

                        with open(file_path, 'r', encoding='utf-8') as f:
                            quiz_data = json.load(f)

                        # Восстанавливаем datetime объекты
                        quiz_data = self._restore_quiz_data_from_save(quiz_data)

                        # Проверяем, не истекло ли время теста
                        if 'end_time' in quiz_data:
                            if quiz_data['end_time'] < datetime.now(timezone.utc):
                                logger.info(f"Quiz for user {user_id} expired, skipping")
                                expired_count += 1
                                # Удаляем файл истекшего теста
                                try:
                                    os.remove(file_path)
                                except:
                                    pass
                                continue

                        # Восстанавливаем тест
                        self.active_quizzes[user_id] = quiz_data
                        restored_count += 1

                    except Exception as e:
                        logger.error(f"Error restoring quiz from {filename}: {e}")
                        # Удаляем поврежденный файл
                        try:
                            os.remove(os.path.join(save_dir, filename))
                        except:
                            pass

            logger.info(f"Restored {restored_count} active quizzes, {expired_count} expired")

        except Exception as e:
            logger.error(f"Error restoring active quizzes: {e}")
            logger.error(traceback.format_exc())

    def _restore_quiz_data_from_save(self, quiz_data: Dict[str, Any]) -> Dict[str, Any]:
        """Восстановление данных теста из сохраненного состояния"""
        # Конвертируем строки обратно в datetime
        if 'start_time' in quiz_data and isinstance(quiz_data['start_time'], str):
            quiz_data['start_time'] = datetime.fromisoformat(quiz_data['start_time'])

        if 'end_time' in quiz_data and isinstance(quiz_data['end_time'], str):
            quiz_data['end_time'] = datetime.fromisoformat(quiz_data['end_time'])

        # Удаляем метаданные сохранения
        quiz_data.pop('_saved_at', None)
        quiz_data.pop('_version', None)

        return quiz_data

    def _cleanup_old_quiz_files(self, save_dir: str):
        """Удаление файлов для неактивных пользователей"""
        try:
            active_user_ids = set(self.active_quizzes.keys())

            for filename in os.listdir(save_dir):
                if filename.startswith('user_') and filename.endswith('.json'):
                    try:
                        user_id = int(filename.replace('user_', '').replace('.json', ''))
                        if user_id not in active_user_ids:
                            file_path = os.path.join(save_dir, filename)
                            os.remove(file_path)
                            logger.debug(f"Removed old quiz file for user {user_id}")
                    except Exception as e:
                        logger.error(f"Error cleaning up file {filename}: {e}")

        except Exception as e:
            logger.error(f"Error in cleanup: {e}")

    async def get_topics_async(self) -> List[Dict[str, Any]]:
        """Асинхронное получение списка тем"""
        try:
            # Используем asyncio.to_thread для синхронной операции с БД
            def fetch_topics():
                with get_session() as session:
                    topics = session.query(Topic).all()
                    return [
                        {
                            "id": t.id,
                            "name": t.name,
                            "description": t.description
                        }
                        for t in topics
                    ]

            return await asyncio.to_thread(fetch_topics)
        except Exception as e:
            logger.error(f"Error fetching topics: {e}")
            return []

    def get_topics(self) -> List[Dict[str, Any]]:
        """Синхронная обертка для совместимости"""
        try:
            loop = asyncio.get_running_loop()
            # Создаем задачу в текущем loop
            future = asyncio.ensure_future(self.get_topics_async())
            # Используем run_in_executor для избежания блокировки
            return loop.run_until_complete(future)
        except RuntimeError:
            # Если нет запущенного loop, создаем новый
            return asyncio.run(self.get_topics_async())

    def start_quiz(self, user_id: int, topic_id: int, question_count: int = None) -> Dict[str, Any]:
        """Начать новый тест для пользователя"""
        logger.info(f"Начинаем тест для пользователя {user_id} по теме {topic_id}")

        # Получаем количество вопросов из настроек, если не указано
        if question_count is None:
            from services.settings_service import get_setting
            question_count = int(get_setting("default_questions_count", "10"))

        with get_session() as session:
            # Получаем вопросы для выбранной темы
            questions = (
                session.query(Question)
                .filter(Question.topic_id == topic_id)
                .order_by(Question.id)
                .all()
            )

            if not questions:
                logger.warning(f"Вопросы для темы {topic_id} не найдены")
                return {"success": False, "message": "Нет доступных вопросов для выбранной темы"}

            # Выбираем случайные вопросы
            selected_count = min(question_count, len(questions))
            logger.info(f"Доступно {len(questions)} вопросов, выбираем {selected_count}")

            selected_questions = random.sample(questions, selected_count)

            # Рассчитываем время окончания теста в зависимости от количества вопросов
            start_time = datetime.now(timezone.utc)
            if question_count <= 10:
                time_limit = 5 * 60  # 5 минут в секундах
            elif question_count <= 15:
                time_limit = 10 * 60  # 10 минут в секундах
            else:
                time_limit = 20 * 60  # 20 минут в секундах

            end_time = start_time + timedelta(seconds=time_limit)

            # Создаём структуру теста
            quiz_data = {
                "topic_id": topic_id,
                "questions": [
                    {
                        "id": q.id,
                        "text": q.text,
                        "options": json.loads(q.options),
                        "correct_answer": json.loads(q.correct_answer),
                        "question_type": q.question_type,
                        "explanation": q.explanation,
                        "media_url": q.media_url
                    }
                    for q in selected_questions
                ],
                "current_question": 0,
                "answers": {},
                "start_time": start_time,
                "end_time": end_time,
                "time_limit": time_limit,
                "is_completed": False
            }

            # Сохраняем тест в активных
            self.active_quizzes[user_id] = quiz_data
            logger.info(
                f"Тест создан для пользователя {user_id} с {len(quiz_data['questions'])} вопросами, лимит времени: {time_limit} сек")

            return {"success": True, "quiz_data": quiz_data}

    def get_current_question(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение текущего вопроса в тесте"""
        if user_id not in self.active_quizzes:
            logger.warning(f"Активный тест для пользователя {user_id} не найден")
            return None

        quiz_data = self.active_quizzes[user_id]

        # Проверка времени
        if "end_time" in quiz_data and datetime.now(timezone.utc) > quiz_data["end_time"]:
            # Время истекло, завершаем тест
            logger.info(f"Время теста для пользователя {user_id} истекло, завершаем")
            quiz_data["is_completed"] = True
            # Завершаем тест с имеющимися ответами
            return None

        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            logger.warning(f"Индекс текущего вопроса превышает количество вопросов для пользователя {user_id}")
            return None

        question = quiz_data["questions"][quiz_data["current_question"]]
        return question


    def format_question_message(self, question: Dict[str, Any], question_num: int, total_questions: int,
                                user_id: int = None) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
        """Форматирование вопроса для отправки в сообщении"""
        # Формируем текст вопроса
        question_text = f"*Вопрос {question_num}/{total_questions}*\n\n{question['text']}"

        # Добавляем информацию о типе вопроса
        if question["question_type"] == "multiple":
            question_text += "\n\n_Выберите все правильные варианты ответов_"
        elif question["question_type"] == "sequence":
            question_text += "\n\n_Расположите варианты в правильном порядке_"

        # Формируем клавиатуру с вариантами ответов
        keyboard = []
        if question["question_type"] == "single" or question["question_type"] == "multiple":
            # Для одиночного или множественного выбора
            for i, option in enumerate(question["options"]):
                button_text = option
                if question["question_type"] == "multiple" and user_id is not None:
                    # Для множественного выбора добавляем чекбоксы
                    selected = self.is_option_selected(user_id, question["id"], i)
                    button_text = f"{'☑' if selected else '☐'} {option}"
                callback_data = f"quiz_answer_{question['id']}_{i}"
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])

            # Добавляем кнопку подтверждения для множественного выбора
            if question["question_type"] == "multiple":
                keyboard.append(
                    [InlineKeyboardButton("✅ Подтвердить выбор", callback_data=f"quiz_confirm_{question['id']}")])

        elif question["question_type"] == "sequence" and user_id is not None:
            # Для вопроса с последовательностью
            current_sequence = self.get_current_sequence(user_id, question["id"])
            if not current_sequence:
                # Показываем все варианты для выбора
                for i, option in enumerate(question["options"]):
                    keyboard.append(
                        [InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"quiz_seq_{question['id']}_{i}")])
            else:
                # Показываем текущую последовательность и оставшиеся варианты
                sequence_text = "\n".join(
                    [f"{i + 1}. {question['options'][int(opt)]}" for i, opt in enumerate(current_sequence)])
                question_text += f"\n\nТекущая последовательность:\n{sequence_text}"

                remaining_options = [i for i in range(len(question["options"])) if str(i) not in current_sequence]
                for i in remaining_options:
                    keyboard.append(
                        [InlineKeyboardButton(question["options"][i], callback_data=f"quiz_seq_{question['id']}_{i}")])

                # Добавляем кнопки сброса и подтверждения
                keyboard.append([
                    InlineKeyboardButton("🔄 Сбросить", callback_data=f"quiz_reset_{question['id']}"),
                    InlineKeyboardButton("✅ Подтвердить", callback_data=f"quiz_confirm_{question['id']}")
                ])
        elif question["question_type"] == "sequence" and user_id is None:
            # Для вопроса с последовательностью, если user_id не указан
            for i, option in enumerate(question["options"]):
                keyboard.append(
                    [InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"quiz_seq_{question['id']}_{i}")])

        # Добавляем кнопку пропуска
        keyboard.append([InlineKeyboardButton("⏩ Пропустить", callback_data="quiz_skip")])

        # Определяем медиа-файл, если есть
        media_file = None
        if question.get("media_url"):
            try:
                media_file = get_image_path(question["media_url"])
                # Проверка существования файла
                if not os.path.exists(media_file):
                    logger.warning(f"Media file not found: {media_file}")
                    media_file = None
            except Exception as e:
                logger.error(f"Error getting media file: {e}")
                media_file = None

        return question_text, InlineKeyboardMarkup(keyboard), media_file

    def is_option_selected(self, user_id: int, question_id: int, option_index: int) -> bool:
        """Проверка, выбран ли вариант ответа в вопросе с множественным выбором"""
        quiz_data = self.active_quizzes.get(user_id, {})
        answers = quiz_data.get("answers", {})
        question_answers = answers.get(str(question_id), [])
        return option_index in question_answers

    def get_current_sequence(self, user_id: int, question_id: int) -> List[str]:
        """Получение текущей последовательности для вопроса с сортировкой"""
        quiz_data = self.active_quizzes.get(user_id, {})
        answers = quiz_data.get("answers", {})
        return answers.get(str(question_id), [])

    def submit_answer(self, user_id: int, question_id: int, answer) -> Dict[str, Any]:
        """Обработка ответа пользователя"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]

        # Проверка времени
        if "end_time" in quiz_data and datetime.now(timezone.utc) > quiz_data["end_time"]:
            # Время истекло, завершаем тест
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result, "message": "Время истекло"}

        question_index = quiz_data["current_question"]

        if question_index >= len(quiz_data["questions"]):
            return {"success": False, "message": "Вопросы закончились"}

        current_question = quiz_data["questions"][question_index]

        # Универсальное преобразование ответа к строке для совместимости
        if current_question["question_type"] == "sequence":
            # Для последовательности - преобразуем каждый элемент к строке
            normalized_answer = [str(a) for a in answer] if isinstance(answer, list) else answer
        else:
            # Для других типов - оставляем как есть
            normalized_answer = answer

        # Сохраняем ответ
        quiz_data["answers"][str(current_question["id"])] = normalized_answer

        # Переходим к следующему вопросу
        quiz_data["current_question"] += 1

        # Проверяем, закончился ли тест
        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result}

        return {"success": True, "is_completed": False}

    def skip_question(self, user_id: int) -> Dict[str, Any]:
        """Пропуск текущего вопроса"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]

        # Проверка времени
        if "end_time" in quiz_data and datetime.now(timezone.utc) > quiz_data["end_time"]:
            # Время истекло, завершаем тест
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result, "message": "Время истекло"}

        question_index = quiz_data["current_question"]

        if question_index >= len(quiz_data["questions"]):
            return {"success": False, "message": "Вопросы закончились"}

        # Переходим к следующему вопросу
        quiz_data["current_question"] += 1

        # Проверяем, закончился ли тест
        if quiz_data["current_question"] >= len(quiz_data["questions"]):
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result}

        return {"success": True, "is_completed": False}

    def check_achievements(self, session, user_id: int, correct_count: int, total_questions: int, percentage: float) -> \
    List[Dict[str, Any]]:
        """Проверка и выдача достижений с использованием существующей сессии"""
        new_achievements = []

        # Получаем пользователя
        user = session.query(User).filter(User.telegram_id == user_id).first()
        if not user:
            return []

        # Получаем уже имеющиеся достижения пользователя
        existing_achievements = {a.name for a in user.achievements}

        # Проверяем условия для разных достижений
        achievements_to_check = [
            # Достижения за прохождение тестов
            {"name": "Первый тест", "description": "Пройден первый тест!", "points": 10,
             "condition": True, "badge_url": "badges/first_test.png"},
            {"name": "Отличник", "description": "Получите 100% в тесте", "points": 50,
             "condition": percentage == 100, "badge_url": "badges/perfect_score.png"},
            {"name": "Знаток истории", "description": "Пройдите 10 тестов", "points": 100,
             "condition": session.query(TestResult).filter(TestResult.user_id == user.id).count() >= 10,
             "badge_url": "badges/history_expert.png"},
        ]

        # Проверяем каждое достижение
        for achievement_data in achievements_to_check:
            if (achievement_data["name"] not in existing_achievements and
                    achievement_data["condition"]):
                # Создаем новое достижение
                achievement = Achievement(
                    user_id=user.id,
                    name=achievement_data["name"],
                    description=achievement_data["description"],
                    badge_url=achievement_data.get("badge_url"),
                    points=achievement_data.get("points", 0)
                )
                session.add(achievement)
                new_achievements.append(achievement_data)

        return new_achievements

    def complete_quiz(self, user_id: int) -> Dict[str, Any]:
        """Завершение теста и подсчет результатов"""
        if user_id not in self.active_quizzes:
            return {"success": False, "message": "Нет активного теста"}

        quiz_data = self.active_quizzes[user_id]
        answers = quiz_data["answers"]
        questions = quiz_data["questions"]

        # Подсчитываем результаты
        correct_count = 0
        total_questions = len(questions)
        question_results = []

        for question in questions:
            question_id = str(question["id"])
            user_answer = answers.get(question_id, None)
            is_correct = False

            if user_answer is not None:
                if question["question_type"] == "single":
                    # Перед доступом к question["correct_answer"][0] проверять длину массива
                    if len(question["correct_answer"]) > 0:
                        is_correct = user_answer == question["correct_answer"][0]
                    else:
                        is_correct = False
                    is_correct = user_answer == question["correct_answer"][0]


                elif question["question_type"] == "sequence":
                    if user_answer is None or question["correct_answer"] is None:
                        is_correct = False
                    else:
                        # Преобразуем оба списка к строкам для корректного сравнения
                        try:
                            user_seq = [str(x) for x in user_answer] if isinstance(user_answer, list) else [
                                str(user_answer)]
                            correct_seq = [str(x) for x in question["correct_answer"]] if isinstance(
                                question["correct_answer"], list) else [str(question["correct_answer"])]
                            is_correct = user_seq == correct_seq
                        except Exception as e:
                            logger.error(f"Ошибка при сравнении последовательностей: {e}")
                            is_correct = False

            question_results.append({
                "question": question["text"],
                "user_answer": user_answer,
                "correct_answer": question["correct_answer"],
                "is_correct": is_correct,
                "explanation": question.get("explanation", "")
            })

            if is_correct:
                correct_count += 1



        # Рассчитываем процент
        percentage = round((correct_count / total_questions) * 100, 1) if total_questions > 0 else 0

        # Вычисляем затраченное время
        start_time = quiz_data["start_time"]
        end_time = datetime.now(timezone.utc)

        # Если тест завершился по времени, используем время окончания из настроек
        if "end_time" in quiz_data and datetime.now(timezone.utc) > quiz_data["end_time"]:
            end_time = quiz_data["end_time"]

        time_spent = int((end_time - start_time).total_seconds())

        # Переменные для хранения данных вне сессии
        user_db_id = None
        user_telegram_id = None

        # Сохраняем результаты в базу
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return {"success": False, "message": "Пользователь не найден"}

            # Сохраняем ID для использования вне сессии
            user_db_id = user.id
            user_telegram_id = user.telegram_id

            # Создаем запись о результатах теста
            test_result = TestResult(
                user_id=user.id,
                topic_id=quiz_data["topic_id"],
                score=correct_count,
                max_score=total_questions,
                percentage=percentage,
                time_spent=time_spent,
                completed_at=datetime.now(timezone.utc)  # Явно указываем время
            )
            session.add(test_result)

            # Проверяем достижения в той же сессии, вместо вызова отдельного метода
            new_achievements = []

            # Проверяем условия для разных достижений
            achievements_to_check = [
                # Достижения за прохождение тестов
                {"name": "Первый тест", "description": "Пройден первый тест!", "points": 10,
                 "condition": True, "badge_url": "badges/first_test.png"},
                {"name": "Отличник", "description": "Получите 100% в тесте", "points": 50,
                 "condition": percentage == 100, "badge_url": "badges/perfect_score.png"},
                {"name": "Знаток истории", "description": "Пройдите 10 тестов", "points": 100,
                 "condition": session.query(TestResult).filter(TestResult.user_id == user.id).count() >= 10,
                 "badge_url": "badges/history_expert.png"},
            ]

            # Получаем уже имеющиеся достижения пользователя
            existing_achievements = {a.name for a in user.achievements}

            # Проверяем каждое достижение
            for achievement_data in achievements_to_check:
                if (achievement_data["name"] not in existing_achievements and
                        achievement_data["condition"]):
                    # Создаем новое достижение
                    achievement = Achievement(
                        user_id=user.id,
                        name=achievement_data["name"],
                        description=achievement_data["description"],
                        badge_url=achievement_data.get("badge_url"),
                        points=achievement_data.get("points", 0)
                    )
                    session.add(achievement)
                    new_achievements.append(achievement_data)

            # Обновляем последнюю активность
            user.last_active = datetime.now(timezone.utc)

            # Фиксируем все изменения в одной транзакции
            session.commit()

            # Обновляем статистику пользователя в той же сессии
            user.last_active = datetime.now(timezone.utc)
            session.commit()

            # Запускаем отправку уведомлений
        notification_service = self.get_notification_service()
        if notification_service and user_db_id:
            try:
                # Используем user_db_id вместо user.id
                notification_task = asyncio.create_task(
                    notification_service.notify_test_completion(
                        user_db_id,  # Используем сохраненный ID
                        {
                            "correct_count": correct_count,
                            "total_questions": total_questions,
                            "percentage": percentage,
                            "topic_id": quiz_data["topic_id"]
                        }
                    )
                )

                # Добавляем обработчик ошибок к задаче
                notification_task.add_done_callback(
                    lambda task: self._handle_notification_task_result(task, user.id)
                )

            except Exception as e:
                logger.error(f"Ошибка при создании задачи отправки уведомления: {e}")
                logger.error(traceback.format_exc())

        # Удаляем тест из активных
        del self.active_quizzes[user_id]

        return {
            "success": True,
            "correct_count": correct_count,
            "total_questions": total_questions,
            "percentage": percentage,
            "question_results": question_results,
            "new_achievements": new_achievements,
            "topic_id": quiz_data["topic_id"],
            "time_spent": time_spent
        }

    def get_user_data(telegram_id: int) -> Optional[Dict[str, Any]]:
        """Безопасное получение данных пользователя"""
        try:
            with get_session() as session:
                user = session.query(User).filter(User.telegram_id == telegram_id).first()
                if not user:
                    return None

                # Копируем все необходимые данные
                return {
                    "id": user.id,
                    "telegram_id": user.telegram_id,
                    "username": user.username,
                    "full_name": user.full_name,
                    "role": user.role,
                    "user_group": user.user_group,
                    "created_at": user.created_at,
                    "last_active": user.last_active,
                    "settings": user.settings
                }
        except Exception as e:
            logger.error(f"Ошибка при получении данных пользователя: {e}")
            return None

    def _handle_notification_task_result(self, task, user_id):
        """Обработка результата задачи отправки уведомления"""
        try:
            # Проверяем, была ли ошибка
            if task.exception():
                logger.error(f"Ошибка при отправке уведомления для пользователя {user_id}: {task.exception()}")
            else:
                logger.info(f"Уведомление для пользователя {user_id} успешно отправлено")
        except Exception as e:
            logger.error(f"Ошибка при обработке результата задачи уведомления: {e}")

    def get_notification_service(self) -> Optional['NotificationService']:
        """Получение сервиса уведомлений"""
        return getattr(self, 'notification_service', None)


