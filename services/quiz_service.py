import json
import random
import os
import logging
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import Question, TestResult, User, Topic, Achievement
from database.db_manager import get_session
from services.notification import NotificationService
from services.stats_service import update_user_stats
from utils.formatters import format_question_text
from utils.image_utils import get_image_path

logger = logging.getLogger(__name__)

class QuizService:
    def __init__(self):
        self.active_quizzes = {}  # словарь активных тестов: {user_id: quiz_data}

    def save_active_quizzes(self):
        """Сохранить состояние активных тестов"""
        try:
            # Создаем директорию, если она не существует
            os.makedirs('data/quiz_state', exist_ok=True)

            # Сохраняем состояние каждого активного теста
            for user_id, quiz_data in self.active_quizzes.items():
                # Глубокая копия данных
                save_data = json.loads(json.dumps(quiz_data, default=self._json_serializer))

                # Преобразуем datetime объект в строку для JSON-сериализации
                if 'start_time' in save_data:
                    save_data['start_time'] = save_data['start_time']

                # Сохраняем в файл
                with open(f'data/quiz_state/user_{user_id}.json', 'w') as f:
                    json.dump(save_data, f)

            logger.info(f"Сохранено {len(self.active_quizzes)} активных тестов")
        except Exception as e:
            logger.error(f"Ошибка при сохранении активных тестов: {e}")
            logger.error(traceback.format_exc())

    def _json_serializer(self, obj):
        """Помощник для сериализации объектов в JSON"""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serializable")

    def restore_active_quizzes(self):
        """Восстановить активные тесты из файлов"""
        try:
            # Проверяем существование директории
            if not os.path.exists('data/quiz_state'):
                logger.info("Директория с сохраненными тестами не найдена")
                return

            # Загружаем каждый сохраненный тест
            for filename in os.listdir('data/quiz_state'):
                if filename.startswith('user_') and filename.endswith('.json'):
                    try:
                        user_id = int(filename.replace('user_', '').replace('.json', ''))

                        with open(f'data/quiz_state/{filename}', 'r') as f:
                            quiz_data = json.load(f)

                        # Преобразуем строку обратно в datetime
                        if 'start_time' in quiz_data:
                            quiz_data['start_time'] = datetime.fromisoformat(quiz_data['start_time'])

                        # Добавляем в активные тесты
                        self.active_quizzes[user_id] = quiz_data
                    except Exception as e:
                        logger.error(f"Ошибка восстановления теста из файла {filename}: {e}")

            logger.info(f"Восстановлено {len(self.active_quizzes)} активных тестов")
        except Exception as e:
            logger.error(f"Ошибка при восстановлении активных тестов: {e}")


    def get_topics(self) -> List[Dict[str, Any]]:
        """Получение списка всех доступных тем для тестирования"""
        with get_session() as session:
            topics = session.query(Topic).all()
            return [{"id": t.id, "name": t.name, "description": t.description} for t in topics]

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
            start_time = datetime.now()
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
        if "end_time" in quiz_data and datetime.now() > quiz_data["end_time"]:
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
        if "end_time" in quiz_data and datetime.now() > quiz_data["end_time"]:
            # Время истекло, завершаем тест
            quiz_data["is_completed"] = True
            result = self.complete_quiz(user_id)
            return {"success": True, "is_completed": True, "result": result, "message": "Время истекло"}

        question_index = quiz_data["current_question"]

        if question_index >= len(quiz_data["questions"]):
            return {"success": False, "message": "Вопросы закончились"}

        current_question = quiz_data["questions"][question_index]

        # Сохраняем ответ
        quiz_data["answers"][str(current_question["id"])] = answer

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
        if "end_time" in quiz_data and datetime.now() > quiz_data["end_time"]:
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

    def check_achievements(self, user_id: int, correct_count: int, total_questions: int, percentage: float) -> List[
        Dict[str, Any]]:
        """Проверка и выдача достижений"""
        new_achievements = []

        with get_session() as session:
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
                 "condition": len(user.results) >= 10, "badge_url": "badges/history_expert.png"},
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

            # Если есть новые достижения, фиксируем изменения
            if new_achievements:
                session.commit()

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
                    is_correct = user_answer == question["correct_answer"][0]
                elif question["question_type"] == "multiple":
                    is_correct = set(user_answer) == set(question["correct_answer"])
                elif question["question_type"] == "sequence":
                    if user_answer is None or question["correct_answer"] is None:
                        is_correct = False
                    else:
                        # Преобразуем оба списка к строкам для корректного сравнения
                        user_seq = [str(x) for x in user_answer]
                        correct_seq = [str(x) for x in question["correct_answer"]]
                        is_correct = user_seq == correct_seq

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
        end_time = datetime.now()

        # Если тест завершился по времени, используем время окончания из настроек
        if "end_time" in quiz_data and datetime.now() > quiz_data["end_time"]:
            end_time = quiz_data["end_time"]

        time_spent = int((end_time - start_time).total_seconds())

        # Сохраняем результаты в базу
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()
            if not user:
                return {"success": False, "message": "Пользователь не найден"}

            # Создаем запись о результатах теста
            test_result = TestResult(
                user_id=user.id,
                topic_id=quiz_data["topic_id"],
                score=correct_count,
                max_score=total_questions,
                percentage=percentage,
                time_spent=time_spent
            )
            session.add(test_result)
            session.commit()

            # Обновляем статистику пользователя
            update_user_stats(user_id)

            # Проверяем достижения
            new_achievements = self.check_achievements(user_id, correct_count, total_questions, percentage)

            try:
                # Пробуем отправить уведомление родителям, если есть notification_service
                notification_service = self.get_notification_service()
                if notification_service:
                    # Создаем задачу, но не ждем ее завершения
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(notification_service.notify_test_completion(
                                user.id,
                                {
                                    "correct_count": correct_count,
                                    "total_questions": total_questions,
                                    "percentage": percentage,
                                    "topic_id": quiz_data["topic_id"]
                                }
                            ))
                    except Exception as e:
                        logger.error(f"Ошибка при создании асинхронной задачи: {e}")
            except Exception as e:
                logger.error(f"Ошибка при отправке уведомления родителям: {e}")

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

    def get_notification_service(self) -> Optional['NotificationService']:
        """Получение сервиса уведомлений"""
        try:
            import inspect
            frame = inspect.currentframe()
            while frame:
                if 'self' in frame.f_locals and hasattr(frame.f_locals['self'], 'notification_service'):
                    return frame.f_locals['self'].notification_service
                frame = frame.f_back
            return None
        except Exception as e:
            logger.error(f"Ошибка при получении сервиса уведомлений: {e}")
            return None

