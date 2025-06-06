import logging
import json
import os
import asyncio
import traceback
from datetime import datetime, timezone

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from services.stats_service import generate_topic_analytics
from database.models import User, Topic, Question, TestResult, Achievement, Notification

from config import ADMINS
import logging
from database.models import BotSettings
from database.db_manager import get_session

# Импортируем клавиатуры
from keyboards.admin_kb import (
    admin_main_keyboard, admin_topics_keyboard, admin_question_type_keyboard,
    admin_edit_topics_keyboard, admin_edit_topic_keyboard, admin_settings_keyboard,
    admin_questions_count_keyboard, admin_reports_keyboard, admin_users_keyboard,
    admin_confirm_delete_keyboard, admin_parent_actions_keyboard, admin_confirm_delete_user_keyboard,
    admin_student_actions_keyboard
)

logger = logging.getLogger(__name__)


def get_db_dialect():
    """Определение диалекта базы данных (PostgreSQL или SQLite)"""
    try:
        with get_session() as session:
            from sqlalchemy import inspect
            connection = session.connection()
            inspector = inspect(connection)
            dialect_name = inspector.engine.dialect.name.lower()
            return dialect_name
    except Exception as e:
        logger.error(f"Ошибка при определении диалекта базы данных: {e}")
        # Возвращаем SQLite по умолчанию
        return "sqlite"


async def show_topics_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показ списка тем для редактирования"""
    query = update.callback_query

    try:
        with get_session() as session:
            # Получаем список тем с созданием копии данных
            topics_data = []
            for topic in session.query(Topic).all():
                topics_data.append({
                    "id": topic.id,
                    "name": topic.name,
                    "description": topic.description
                })

        # Форматируем текст со списком тем
        topics_text = "✏️ *Темы для тестирования*\n\n"

        if not topics_data:
            topics_text += "Список тем пуст. Создайте первую тему."
        else:
            for topic in topics_data:
                topics_text += f"• *{topic['name']}*\n"
                if topic['description']:
                    topics_text += f"  _{topic['description']}_\n"

        # Используем готовую клавиатуру
        reply_markup = admin_edit_topics_keyboard(topics_data)

        await query.edit_message_text(
            topics_text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in show_topics_list: {e}")
        await query.edit_message_text(
            f"Произошла ошибка при получении списка тем: {str(e)}\n\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
        )

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


class AdminHandler:
    def __init__(self):
        self.context = None
        self.query = None
        self.quiz_service = None
        self.parent_service = None

    def init_services(self, quiz_service_inst=None, parent_service_inst=None):
        """Инициализация сервисов в классе"""
        if quiz_service_inst:
            self.quiz_service = quiz_service_inst

        if parent_service_inst:
            self.parent_service = parent_service_inst

    async def handle_topic_edit_action(self, update, context, action_type, topic_id):
        """Общая логика обработки действий редактирования темы"""
        query = update.callback_query

        with get_session() as session:
            topic = session.query(Topic).get(topic_id)
            if not topic:
                await query.edit_message_text("Тема не найдена.")
                return False

            # Сохраняем необходимые данные из темы, пока сессия активна
            topic_name = topic.name
            topic_description = topic.description

            # Обрабатываем разные типы действий
            if action_type == "name":
                await query.edit_message_text(
                    f"Введите новое название для темы '{topic_name}':\n\n"
                    "Отправьте текст в следующем сообщении."
                )

                # Устанавливаем состояние
                context.user_data["admin_state"] = "editing_topic_name"
                context.user_data["editing_topic_id"] = topic_id
                logger.info(f"Установлено состояние editing_topic_name для темы {topic_id}")

            elif action_type == "desc":
                await query.edit_message_text(
                    f"Введите новое описание для темы '{topic_name}':\n\n"
                    f"Текущее описание: {topic_description or 'Нет описания'}\n\n"
                    "Отправьте текст в следующем сообщении."
                )

                # Устанавливаем состояние
                context.user_data["admin_state"] = "editing_topic_description"
                context.user_data["editing_topic_id"] = topic_id
                logger.info(f"Установлено состояние editing_topic_description для темы {topic_id}")

            elif action_type == "delete":
                # Проверяем, есть ли вопросы, связанные с этой темой
                questions_count = session.query(Question).filter(Question.topic_id == topic_id).count()

                warning_text = ""
                if questions_count > 0:
                    warning_text = f"\n⚠️ ВНИМАНИЕ! К этой теме привязано {questions_count} вопросов. При удалении темы все связанные вопросы также будут удалены."

                # Используем готовую клавиатуру для подтверждения
                reply_markup = admin_confirm_delete_keyboard(topic_id)

                await query.edit_message_text(
                    f"Вы уверены, что хотите удалить тему '{topic_name}'?{warning_text}",
                    reply_markup=reply_markup
                )
            else:
                return False

        return True

    async def export_to_excel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /export_excel для экспорта данных в Excel"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для экспорта данных."
            )
            return

        # Показываем меню выбора типа экспорта
        keyboard = [
            [
                InlineKeyboardButton("📊 Результаты тестов", callback_data="admin_export_results"),
                InlineKeyboardButton("📈 Статистика по темам", callback_data="admin_export_topics")
            ],
            [
                InlineKeyboardButton("👨‍🎓 Прогресс учеников", callback_data="admin_export_students"),
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Выберите тип данных для экспорта:",
            reply_markup=reply_markup
        )

    async def show_problematic_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ списка проблемных вопросов для администратора"""
        query = update.callback_query
        user_id = update.effective_user.id

        # Проверка прав администратора
        if str(user_id) not in ADMINS:
            await query.edit_message_text(
                "У вас нет прав для доступа к этой информации."
            )
            return

        try:
            # Получаем статистику проблемных вопросов
            from services.stats_service import get_problematic_questions
            result = get_problematic_questions(limit=10)

            if not result["success"]:
                await query.edit_message_text(
                    f"Ошибка при получении статистики: {result['message']}"
                )
                return

            if not result.get("has_data", False):
                # Создаем клавиатуру для возврата
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_topic_stats")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    "Нет данных о проблемных вопросах. Возможно, еще не было пройдено достаточно тестов.",
                    reply_markup=reply_markup
                )
                return

            # Формируем текст с проблемными вопросами
            problematic_questions = result["problematic_questions"]

            text = "🔴 *Самые проблемные вопросы*\n\n"

            for i, question in enumerate(problematic_questions, 1):
                short_question = question["question_text"][:50] + "..." if len(question["question_text"]) > 50 else \
                    question["question_text"]
                text += f"{i}. *{short_question}*\n"
                text += f"   Тема: {question['topic_name']}\n"
                text += f"   Процент ошибок: {question['error_rate']}%\n"
                text += f"   Всего ответов: {question['total_answers']}\n\n"

            # Создаем клавиатуру для возврата и просмотра детальной информации
            keyboard = [
                [InlineKeyboardButton("📊 Детальный анализ", callback_data="admin_question_analysis")],
                [InlineKeyboardButton("🔙 Назад к статистике", callback_data="admin_topic_stats")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем сообщение с текстом
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            # Если есть график, отправляем его отдельным сообщением
            if "chart" in result and result["chart"]:
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=result["chart"],
                    caption="📊 Топ-5 самых сложных вопросов (процент ошибок)"
                )

        except Exception as e:
            logger.error(f"Error in show_problematic_questions: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении статистики проблемных вопросов: {str(e)}"
            )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /admin для открытия панели администратора"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для доступа к панели администратора."
            )
            return

        # Используем готовую клавиатуру
        reply_markup = admin_main_keyboard()

        await update.message.reply_text(
            "👨‍💻 *Панель администратора*\n\n"
            "Выберите действие из списка ниже:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def show_topics_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ списка тем для редактирования"""
        query = update.callback_query

        try:
            with get_session() as session:
                # ВАЖНО: Создаем копии данных, пока сессия активна
                topics_data = []
                for topic in session.query(Topic).all():
                    # Копируем все необходимые данные
                    topics_data.append({
                        "id": topic.id,
                        "name": topic.name,
                        "description": topic.description,
                        # Добавляем другие поля если нужно
                    })
                # Сессия закроется автоматически при выходе из with блока

            # Форматируем текст со списком тем
            topics_text = "✏️ *Темы для тестирования*\n\n"

            if not topics_data:
                topics_text += "Список тем пуст. Создайте первую тему."
            else:
                for topic in topics_data:
                    topics_text += f"• *{topic['name']}*\n"
                    if topic.get('description'):
                        topics_text += f"  _{topic['description']}_\n"

            # Используем готовую клавиатуру
            reply_markup = admin_edit_topics_keyboard(topics_data)

            await query.edit_message_text(
                topics_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error in show_topics_list: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении списка тем: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def add_question(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /add_question для добавления нового вопроса"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для добавления вопросов."
            )
            return

        # Получаем список тем для выбора
        with get_session() as session:
            topics = session.query(Topic).all()
            # Преобразуем объекты в словари для передачи в функцию клавиатуры
            topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

        if not topics:
            await update.message.reply_text(
                "Сначала необходимо создать хотя бы одну тему. Используйте /admin -> Редактировать темы."
            )
            return

        # Используем готовую клавиатуру
        reply_markup = admin_topics_keyboard(topics_data)

        await update.message.reply_text(
            "Выберите тему для нового вопроса:",
            reply_markup=reply_markup
        )

        # Устанавливаем состояние для пользователя
        context.user_data["admin_state"] = "adding_question"

    async def show_student_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, student_id: int) -> None:
        """Показ подробной информации об ученике"""
        query = update.callback_query

        try:
            with get_session() as session:
                student = session.query(User).get(student_id)

                if not student or student.role != "student":
                    await query.edit_message_text("Ученик не найден.")
                    return

                # Собираем данные об ученике
                name = student.full_name or student.username or f"Ученик {student.id}"
                telegram_id = student.telegram_id
                created_at = student.created_at.strftime('%d.%m.%Y %H:%M') if student.created_at else "Неизвестно"
                last_active = student.last_active.strftime('%d.%m.%Y %H:%M') if student.last_active else "Никогда"

                # Статистика тестов
                test_count = session.query(TestResult).filter(TestResult.user_id == student.id).count()

                # Достижения
                achievements_count = session.query(Achievement).filter(Achievement.user_id == student.id).count()

                # Связанные родители
                parents = []
                for parent in student.parents:
                    parent_name = parent.full_name or parent.username or f"Родитель {parent.id}"
                    parents.append(parent_name)

                # Формируем текст
                details_text = f"📋 *Информация об ученике*\n\n"
                details_text += f"*Имя:* {name}\n"
                details_text += f"*Telegram ID:* {telegram_id}\n"
                details_text += f"*Дата регистрации:* {created_at}\n"
                details_text += f"*Последняя активность:* {last_active}\n\n"

                details_text += f"*Статистика:*\n"
                details_text += f"• Пройдено тестов: {test_count}\n"
                details_text += f"• Достижений: {achievements_count}\n\n"

                details_text += f"*Связанные родители ({len(parents)}):*\n"
                if parents:
                    for parent_name in parents:
                        details_text += f"• {parent_name}\n"
                else:
                    details_text += "Нет связанных родителей\n"

                # Создаем клавиатуру для действий с учеником
                reply_markup = admin_student_actions_keyboard(student_id)

                await query.edit_message_text(
                    details_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in show_student_details: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении информации об ученике: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def show_parent_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, parent_id: int) -> None:
        """Показ подробной информации о родителе"""
        query = update.callback_query

        try:
            with get_session() as session:
                parent = session.query(User).get(parent_id)

                if not parent or parent.role != "parent":
                    await query.edit_message_text("Родитель не найден.")
                    return

                # Собираем данные о родителе
                name = parent.full_name or parent.username or f"Родитель {parent.id}"
                telegram_id = parent.telegram_id
                created_at = parent.created_at.strftime('%d.%m.%Y %H:%M') if parent.created_at else "Неизвестно"
                last_active = parent.last_active.strftime('%d.%m.%Y %H:%M') if parent.last_active else "Никогда"

                # Настройки
                settings = {}
                if parent.settings:
                    try:
                        settings = json.loads(parent.settings)
                    except json.JSONDecodeError:
                        settings = {}

                # Связанные ученики
                children = []
                for child in parent.children:
                    child_name = child.full_name or child.username or f"Ученик {child.id}"
                    children.append((child.id, child_name))

                # Формируем текст
                details_text = f"📋 *Информация о родителе*\n\n"
                details_text += f"*Имя:* {name}\n"
                details_text += f"*Telegram ID:* {telegram_id}\n"
                details_text += f"*Дата регистрации:* {created_at}\n"
                details_text += f"*Последняя активность:* {last_active}\n\n"

                details_text += f"*Связанные ученики ({len(children)}):*\n"
                if children:
                    for _, child_name in children:
                        details_text += f"• {child_name}\n"
                else:
                    details_text += "Нет связанных учеников\n"

                # Создаем клавиатуру для действий с родителем
                reply_markup = admin_parent_actions_keyboard(parent_id)

                await query.edit_message_text(
                    details_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in show_parent_details: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении информации о родителе: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def confirm_delete_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                  user_type: str) -> None:
        """Подтверждение удаления пользователя"""
        query = update.callback_query

        try:
            with get_session() as session:
                user = session.query(User).get(user_id)

                if not user:
                    await query.edit_message_text("Пользователь не найден.")
                    return

                name = user.full_name or user.username or f"Пользователь {user.id}"

                # Определение текста в зависимости от типа пользователя
                user_type_text = "ученика" if user_type == "student" else "родителя"

                # Предупреждения в зависимости от типа пользователя
                warning_text = ""
                if user_type == "student":
                    # Для ученика проверяем связанные данные
                    test_count = session.query(TestResult).filter(TestResult.user_id == user.id).count()
                    achievements_count = session.query(Achievement).filter(Achievement.user_id == user.id).count()
                    parents_count = len(user.parents)

                    if test_count > 0 or achievements_count > 0 or parents_count > 0:
                        warning_text += "\n\n⚠️ При удалении ученика будут также удалены:\n"
                        if test_count > 0:
                            warning_text += f"• Результаты {test_count} тестов\n"
                        if achievements_count > 0:
                            warning_text += f"• {achievements_count} достижений\n"
                        if parents_count > 0:
                            warning_text += f"• Связи с {parents_count} родителями\n"

                elif user_type == "parent":
                    # Для родителя проверяем связанных учеников
                    children_count = len(user.children)

                    if children_count > 0:
                        warning_text += "\n\n⚠️ При удалении родителя будут удалены связи с учениками. Сами ученики и их данные не будут затронуты."

                # Формируем сообщение
                confirm_text = f"❓ Вы действительно хотите удалить {user_type_text} *{name}*?{warning_text}\n\n"
                confirm_text += "Это действие нельзя отменить."

                # Клавиатура для подтверждения
                reply_markup = admin_confirm_delete_user_keyboard(user_id, user_type)

                await query.edit_message_text(
                    confirm_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in confirm_delete_user: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при подготовке к удалению пользователя: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def delete_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                          user_type: str) -> None:
        """Удаление пользователя и всех связанных данных"""
        query = update.callback_query

        try:
            user_name = None
            success = False

            with get_session() as session:
                user = session.query(User).get(user_id)
                if not user:
                    await query.edit_message_text("Пользователь не найден.")
                    return

                # Сохраняем имя пользователя перед удалением
                user_name = user.full_name or user.username or f"Пользователь {user.id}"

                # Удаляем связанные данные в зависимости от типа пользователя
                if user_type == "student":
                    # Получаем все ID результатов тестов пользователя
                    test_result_ids = [r.id for r in
                                       session.query(TestResult).filter(TestResult.user_id == user.id).all()]

                    # Сначала удаляем записи из промежуточной таблицы 'question_result'
                    if test_result_ids:
                        # Используем прямой SQL запрос, так как таблица определена как Table, а не класс
                        from sqlalchemy import text
                        for test_id in test_result_ids:
                            session.execute(
                                text("DELETE FROM question_result WHERE test_result_id = :test_id"),
                                {"test_id": test_id}
                            )
                        # Или удаляем одним запросом
                        # placeholders = ','.join([':id'+str(i) for i in range(len(test_result_ids))])
                        # params = {f'id{i}': id_val for i, id_val in enumerate(test_result_ids)}
                        # session.execute(
                        #     text(f"DELETE FROM question_result WHERE test_result_id IN ({placeholders})"),
                        #     params
                        # )

                    # Теперь можно безопасно удалить результаты тестов
                    session.query(TestResult).filter(TestResult.user_id == user.id).delete()

                    # Удаляем достижения
                    session.query(Achievement).filter(Achievement.user_id == user.id).delete()

                    # Удаляем уведомления
                    session.query(Notification).filter(Notification.user_id == user.id).delete()

                    # Явно отвязываем родителей для решения проблем с foreign key
                    for parent in user.parents:
                        parent.children.remove(user)

                elif user_type == "parent":
                    # Удаляем уведомления
                    session.query(Notification).filter(Notification.user_id == user.id).delete()

                    # Явно отвязываем детей
                    user.children = []

                # Применяем изменения до удаления пользователя
                session.flush()

                # Удаляем самого пользователя
                session.delete(user)
                session.commit()
                success = True

            if success and user_name:
                user_type_text = "Ученик" if user_type == "student" else "Родитель"
                await query.edit_message_text(
                    f"✅ {user_type_text} *{user_name}* успешно удален вместе со всеми связанными данными.",
                    parse_mode="Markdown"
                )

                # Возвращаемся к соответствующему списку после небольшой паузы
                await asyncio.sleep(2)
                if user_type == "student":
                    await self.show_students_list(update, context)
                else:
                    await self.show_parents_list(update, context)
            else:
                await query.edit_message_text(
                    "Произошла ошибка при удалении пользователя."
                )

        except Exception as e:
            logger.error(f"Error in delete_user: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при удалении пользователя: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def import_questions(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /import для импорта вопросов из JSON файла"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для импорта вопросов."
            )
            return

        await update.message.reply_text(
            "Для импорта вопросов отправьте JSON файл с вопросами.\n\n"
            "Структура файла должна соответствовать формату:\n"
            "```\n"
            "{\n"
            '  "topic": {\n'
            '    "id": 1,\n'
            '    "name": "Название темы",\n'
            '    "description": "Описание темы"\n'
            "  },\n"
            '  "questions": [\n'
            "    {\n"
            '      "id": 1,\n'
            '      "text": "Текст вопроса",\n'
            '      "options": ["Вариант 1", "Вариант 2", ...],\n'
            '      "correct_answer": [0],\n'
            '      "question_type": "single",\n'
            '      "difficulty": 1,\n'
            '      "explanation": "Объяснение ответа"\n'
            "    },\n"
            "    ...\n"
            "  ]\n"
            "}\n"
            "```\n\n"
            "Или просто используйте команду /admin и выберите 'Импорт вопросов'.",
            parse_mode="Markdown"
        )

        # Устанавливаем состояние для пользователя
        context.user_data["admin_state"] = "importing_questions"

    async def show_results_dynamics(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ динамики результатов тестирования"""
        query = update.callback_query
        user_id = update.effective_user.id

        # Проверка прав администратора
        if str(user_id) not in ADMINS:
            await query.edit_message_text(
                "У вас нет прав для доступа к этой информации."
            )
            return

        try:
            # Получаем статистику по динамике за последний месяц
            with get_session() as session:
                # Получаем данные за последний месяц
                from datetime import datetime, timedelta
                month_ago = datetime.utcnow() - timedelta(days=30)

                # Получаем результаты тестов
                results = session.query(TestResult).filter(
                    TestResult.completed_at >= month_ago
                ).order_by(TestResult.completed_at).all()

                if not results:
                    # Используем готовую клавиатуру для возврата
                    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")]]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        "Нет данных о результатах тестов за последний месяц.",
                        reply_markup=reply_markup
                    )
                    return

                # Группируем результаты по дням
                import pandas as pd
                results_data = []
                for result in results:
                    results_data.append({
                        "date": result.completed_at.date(),
                        "percentage": result.percentage
                    })

                df = pd.DataFrame(results_data)
                daily_avg = df.groupby("date")["percentage"].mean().reset_index()

                # Создаем график
                import matplotlib.pyplot as plt
                from io import BytesIO

                fig, ax = plt.subplots(figsize=(10, 6))
                ax.plot(daily_avg["date"], daily_avg["percentage"], marker='o', linestyle='-')

                ax.set_title("Динамика результатов тестирования за последний месяц")
                ax.set_xlabel("Дата")
                ax.set_ylabel("Средний процент")
                ax.grid(True)
                plt.xticks(rotation=45)
                plt.tight_layout()

                # Сохраняем график в буфер
                img_buf = BytesIO()
                plt.savefig(img_buf, format='png')
                img_buf.seek(0)
                plt.close()

                # Отправляем текст
                text = "📈 *Динамика результатов тестирования*\n\n"
                text += f"• Период: последние 30 дней\n"
                text += f"• Всего тестов: {len(results)}\n"
                text += f"• Средний результат: {df['percentage'].mean():.1f}%\n"

                # Рассчитываем тренд (улучшение или ухудшение)
                if len(daily_avg) > 1:
                    first_week = df[df["date"] <= df["date"].min() + timedelta(days=7)]["percentage"].mean()
                    last_week = df[df["date"] >= df["date"].max() - timedelta(days=7)]["percentage"].mean()
                    trend_diff = last_week - first_week

                    if abs(trend_diff) > 0.1:
                        trend_text = "улучшение" if trend_diff > 0 else "ухудшение"
                        text += f"• Тренд: {trend_text} на {abs(trend_diff):.1f}%\n"

                # Создаем клавиатуру
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

                # Отправляем график
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=img_buf,
                    caption="Динамика средних результатов по дням"
                )

        except Exception as e:
            logger.error(f"Error in show_results_dynamics: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении динамики результатов: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
                ]])
            )

    async def show_question_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ детального анализа проблемных вопросов"""
        query = update.callback_query
        user_id = update.effective_user.id

        # Проверка прав администратора
        if str(user_id) not in ADMINS:
            await query.edit_message_text(
                "У вас нет прав для доступа к этой информации."
            )
            return

        try:
            # Получаем расширенную статистику проблемных вопросов
            from services.stats_service import get_problematic_questions
            result = get_problematic_questions(limit=20)  # Увеличиваем лимит для подробного анализа

            if not result["success"]:
                await query.edit_message_text(
                    f"Ошибка при получении статистики: {result['message']}"
                )
                return

            if not result.get("has_data", False):
                # Создаем клавиатуру для возврата
                keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="admin_problematic_questions")]]
                reply_markup = InlineKeyboardMarkup(keyboard)

                await query.edit_message_text(
                    "Нет данных о проблемных вопросах для детального анализа. Возможно, еще не было пройдено достаточно тестов.",
                    reply_markup=reply_markup
                )
                return

            # Форматируем текст с детальным анализом
            problematic_questions = result["problematic_questions"]

            # Сортируем вопросы по уровню ошибок
            problematic_questions.sort(key=lambda q: q["error_rate"], reverse=True)

            text = "🔍 *Детальный анализ проблемных вопросов*\n\n"
            text += "Ниже представлен подробный анализ вопросов, вызывающих наибольшие затруднения у учеников.\n\n"

            # Группируем вопросы по темам
            topics_data = {}
            for question in problematic_questions:
                topic_id = question["topic_id"]
                if topic_id not in topics_data:
                    topics_data[topic_id] = {
                        "name": question["topic_name"],
                        "questions": [],
                        "avg_error_rate": 0
                    }
                topics_data[topic_id]["questions"].append(question)

            # Рассчитываем средний процент ошибок для каждой темы
            for topic_id, topic_data in topics_data.items():
                if topic_data["questions"]:
                    topic_data["avg_error_rate"] = sum(q["error_rate"] for q in topic_data["questions"]) / len(
                        topic_data["questions"])

            # Сортируем темы по среднему проценту ошибок
            sorted_topics = sorted(topics_data.items(), key=lambda x: x[1]["avg_error_rate"], reverse=True)

            # Выводим статистику по темам
            text += "*Статистика по темам:*\n"
            for topic_id, topic_data in sorted_topics:
                topic_name = topic_data["name"]
                avg_error = topic_data["avg_error_rate"]
                questions_count = len(topic_data["questions"])

                text += f"• *{topic_name}*: {avg_error:.1f}% ошибок (всего вопросов: {questions_count})\n"

            text += "\n*Топ-10 самых проблемных вопросов:*\n"
            for i, question in enumerate(problematic_questions[:10], 1):
                short_question = question["question_text"][:50] + "..." if len(question["question_text"]) > 50 else \
                question["question_text"]
                text += f"{i}. *{short_question}*\n"
                text += f"   Тема: {question['topic_name']}\n"
                text += f"   Процент ошибок: {question['error_rate']}%\n"
                text += f"   Всего ответов: {question['total_answers']}\n\n"

            # Рекомендации по улучшению
            text += "*Рекомендации:*\n"
            text += "• Обратите внимание на темы с высоким процентом ошибок\n"
            text += "• Рассмотрите возможность пересмотра формулировок сложных вопросов\n"
            text += "• Добавьте подробные объяснения к проблемным вопросам\n"
            text += "• Создайте дополнительные материалы по сложным темам\n"

            # Создаем клавиатуру для возврата
            keyboard = [
                [InlineKeyboardButton("🔙 Назад к проблемным вопросам", callback_data="admin_problematic_questions")]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем сообщение с текстом
            await query.edit_message_text(
                text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

        except Exception as e:
            logger.error(f"Error in show_question_analysis: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при анализе проблемных вопросов: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="admin_problematic_questions")
                ]])
            )

    async def handle_admin_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик нажатий кнопок в панели администратора"""
        global new_state
        query = update.callback_query
        callback_data = query.data
        user_id = update.effective_user.id

        logger.debug(f"Processing button {callback_data} from user {user_id}")

        await query.answer()

        # Дополнительные проверки callback-данных
        logger.info(f"Обработка кнопки администратора: {query.data}")

        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await query.edit_message_text(
                "У вас нет прав для доступа к панели администратора."
            )
            return

        try:
            # Используем контекстный менеджер для всех операций с базой данных
            if query.data == "admin_problematic_questions":
                # Показываем список проблемных вопросов
                await self.show_problematic_questions(update, context)

            elif query.data == "admin_results_dynamics":
            # Показываем динамику результатов
                await self.show_results_dynamics(update, context)



            elif query.data == "admin_export":
                keyboard = [
                    [
                        InlineKeyboardButton("📊 Результаты тестов", callback_data="admin_export_results"),
                        InlineKeyboardButton("📈 Статистика по темам", callback_data="admin_export_topics")
                    ],
                    [
                        InlineKeyboardButton("👨‍🎓 Прогресс учеников", callback_data="admin_export_students"),
                        InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    "Выберите тип данных для экспорта:",
                    reply_markup=reply_markup
                )
            elif query.data == "admin_topic_stats":
                # Показываем статистику по темам
                await self.show_topic_stats(update, context)

            elif query.data == "admin_users":
                # Показываем список пользователей
                await self.show_users_list(update, context)

            elif query.data == "admin_edit_topics":
                # Показываем список тем для редактирования
                await show_topics_list(update, context)

            elif query.data == "admin_add_question":
                # Переход к добавлению вопроса
                with get_session() as session:
                    topics = session.query(Topic).all()
                    # Преобразуем объекты в словари для передачи в функцию клавиатуры
                    topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

                if not topics_data:
                    await query.edit_message_text(
                        "Сначала необходимо создать хотя бы одну тему. Используйте 'Редактировать темы'."
                    )
                    return

                # Используем готовую клавиатуру
                reply_markup = admin_topics_keyboard(topics_data)

                await query.edit_message_text(
                    "Выберите тему для нового вопроса:",
                    reply_markup=reply_markup
                )

                # Устанавливаем состояние для пользователя
                context.user_data["admin_state"] = "adding_question"

            elif query.data == "admin_import":
                # Инструкция по импорту вопросов
                await query.edit_message_text(
                    "Для импорта вопросов отправьте JSON файл с вопросами.\n\n"
                    "Структура файла должна соответствовать формату:\n"
                    "```\n"
                    "{\n"
                    '  "topic": {\n'
                    '    "id": 1,\n'
                    '    "name": "Название темы",\n'
                    '    "description": "Описание темы"\n'
                    "  },\n"
                    '  "questions": [\n'
                    "    {\n"
                    '      "id": 1,\n'
                    '      "text": "Текст вопроса",\n'
                    '      "options": ["Вариант 1", "Вариант 2", ...],\n'
                    '      "correct_answer": [0],\n'
                    '      "question_type": "single",\n'
                    '      "difficulty": 1,\n'
                    '      "explanation": "Объяснение ответа"\n'
                    "    },\n"
                    "    ...\n"
                    "  ]\n"
                    "}\n"
                    "```\n\n"
                    "Отправьте файл как документ в этот чат.",
                    parse_mode="Markdown"
                )

                # Устанавливаем состояние для пользователя
                context.user_data["admin_state"] = "importing_questions"


            elif query.data.startswith("admin_export_"):
                export_action = query.data.replace("admin_export_", "")

                if export_action == "results":
                    # Показать меню выбора периода для результатов тестов
                    keyboard = [
                        [
                            InlineKeyboardButton("За неделю", callback_data="admin_export_results_week"),
                            InlineKeyboardButton("За месяц", callback_data="admin_export_results_month")
                        ],
                        [
                            InlineKeyboardButton("За год", callback_data="admin_export_results_year"),
                            InlineKeyboardButton("За всё время", callback_data="admin_export_results_all")
                        ],
                        [
                            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
                        ]
                    ]

                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await query.edit_message_text(
                        "Выберите период для экспорта результатов тестов:",
                        reply_markup=reply_markup
                    )
                elif export_action == "topics":
                    # Сразу экспортируем статистику по темам
                    await self.handle_export_button(update, context, "topics")
                elif export_action == "students":
                    # Сразу экспортируем прогресс учеников
                    await self.handle_export_button(update, context, "students")
                elif export_action.startswith("results_"):
                    # Экспорт результатов тестов за период
                    period = export_action.replace("results_", "")
                    await self.handle_export_button(update, context, "results", period)

            elif query.data.startswith("admin_edit_topics_"):

                # Редактирование выбранной темы, только если это прямой вызов без суффиксов name/desc

                if not any(x in query.data for x in ["name_", "desc_"]):

                    topic_id = int(query.data.replace("admin_edit_topics_", ""))

                    with get_session() as session:

                        topic = session.query(Topic).get(topic_id)

                        if not topic:
                            await query.edit_message_text(
                                "Тема не найдена."
                            )
                            return
                        # Используем готовую клавиатуру
                        reply_markup = admin_edit_topic_keyboard(topic_id)
                        await query.edit_message_text(
                            f"*Редактирование темы:* {topic.name}\n\n"
                            f"*Описание:* {topic.description or 'Нет описания'}\n\n"
                            "Выберите действие:",
                            reply_markup=reply_markup,
                            parse_mode="Markdown"
                        )


            elif query.data == "admin_back_topics_list":
                # Возврат к списку тем
                await self.show_topics_list(update, context)

            # Обработчики для редактирования тем - с исправленными проверками
            elif query.data.startswith("admin_edit_topic_name_"):
                topic_id = int(query.data.replace("admin_edit_topic_name_", ""))
                logger.info(f"Изменение названия темы с ID {topic_id}")
                await self.handle_topic_edit_action(update, context, "name", topic_id)
            elif query.data.startswith("admin_edit_topic_desc_"):
                topic_id = int(query.data.replace("admin_edit_topic_desc_", ""))
                logger.info(f"Изменение описания темы с ID {topic_id}")
                await self.handle_topic_edit_action(update, context, "desc", topic_id)

            elif query.data.startswith("admin_delete_topic_"):
                topic_id = int(query.data.replace("admin_delete_topic_", ""))
                logger.info(f"Запрос на удаление темы с ID {topic_id}")
                with get_session() as session:
                    topic = session.query(Topic).get(topic_id)
                    if not topic:
                        await query.edit_message_text("Тема не найдена.")
                        return
                    # Сохраняем имя темы и количество вопросов
                    topic_name = topic.name
                    questions_count = session.query(Question).filter(Question.topic_id == topic_id).count()
                # Используем готовую клавиатуру для подтверждения
                reply_markup = admin_confirm_delete_keyboard(topic_id)
                warning_text = ""
                if questions_count > 0:
                    warning_text = f"\n⚠️ ВНИМАНИЕ! К этой теме привязано {questions_count} вопросов. При удалении темы все связанные вопросы также будут удалены."
                await query.edit_message_text(
                    f"Вы уверены, что хотите удалить тему '{topic_name}'?{warning_text}",
                    reply_markup=reply_markup

                )

            elif query.data == "admin_settings":
                # Настройки бота
                await self.show_bot_settings(update, context)

            elif query.data == "admin_setting_questions_count":
                # Обработка настройки количества вопросов в тесте
                reply_markup = admin_questions_count_keyboard()
                await query.edit_message_text(
                    "Укажите количество вопросов в тесте по умолчанию (от 5 до 20):",
                    reply_markup=reply_markup
                )


            elif query.data == "admin_setting_reports":
                # Обработка настройки отчетов родителям
                from config import ENABLE_PARENT_REPORTS
                current_state = "включены" if ENABLE_PARENT_REPORTS else "отключены"
                reply_markup = admin_reports_keyboard()
                await query.edit_message_text(
                    f"Автоматические отчеты родителям сейчас {current_state}.\n\n"
                    "Выберите действие:",
                    reply_markup=reply_markup
                )

            elif query.data == "admin_setting_questions_count":
                # Обработка настройки количества вопросов в тесте
                from services.settings_service import get_setting
                default_questions_count = get_setting("default_questions_count", "10")
                reply_markup = admin_questions_count_keyboard()
                await query.edit_message_text(
                    f"Текущее количество вопросов в тесте: {default_questions_count}\n\n"
                    "Выберите новое количество вопросов:",
                    reply_markup=reply_markup
                )

            elif query.data.startswith("admin_reports_"):
                # Включение/отключение отчетов
                action = query.data.replace("admin_reports_", "")

                try:
                    # Здесь код для изменения настройки
                    # Например, через изменение переменной окружения или config файла
                    import os
                    from dotenv import load_dotenv, set_key
                    # Путь к файлу .env
                    env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
                    new_state = "включены" if action == "enable" else "отключены"
                    # Если файл .env существует, обновляем его
                    if os.path.exists(env_path):
                        # Устанавливаем новое значение
                        set_key(env_path, "ENABLE_PARENT_REPORTS", "true" if action == "enable" else "false")

                        # Перезагружаем переменные окружения
                        load_dotenv(override=True)

                        # Обновляем значение в конфигурации
                        from config import ENABLE_PARENT_REPORTS
                        new_state = "включены" if action == "enable" else "отключены"

                        await query.edit_message_text(
                            f"✅ Автоматические отчеты родителям {new_state}.\n\n"
                            "Настройка применена.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                            ]])
                        )

                    else:
                        # Если файл .env не существует, сообщаем об ошибке
                        await query.edit_message_text(
                            "Файл конфигурации не найден. Настройка не может быть изменена автоматически.\n"
                            "Пожалуйста, измените значение ENABLE_PARENT_REPORTS вручную в файле конфигурации.",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                            ]])
                        )
                except Exception as e:
                    logger.error(f"Error changing parent reports setting: {e}")
                    await query.edit_message_text(
                        f"Произошла ошибка при изменении настроек: {str(e)}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
                        ]])
                    )

                    await query.edit_message_text(
                        f"✅ Автоматические отчеты родителям {new_state}.\n\n"
                        "Настройка будет применена при следующем запуске бота.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                        ]])
                    )

            elif query.data.startswith("admin_set_questions_"):
                # Установка количества вопросов
                count = query.data.replace("admin_set_questions_", "")

                try:
                    from services.settings_service import set_setting
                    set_setting("default_questions_count", count)

                    # Определяем время в зависимости от количества вопросов
                    questions_count = int(count)
                    if questions_count <= 10:
                        time_minutes = 5
                    elif questions_count <= 15:
                        time_minutes = 10
                    else:
                        time_minutes = 20

                    await query.edit_message_text(
                        f"✅ Количество вопросов в тесте изменено на {count}.\n"
                        f"Время на прохождение теста: {time_minutes} минут.\n\n"
                        "Настройка будет применена к новым тестам.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад к настройкам", callback_data="admin_settings")
                        ]])
                    )
                except Exception as e:
                    logger.error(f"Error setting questions count: {e}")
                    await query.edit_message_text(
                        f"Произошла ошибка при изменении настроек: {str(e)}",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
                        ]])
                    )

            elif query.data.startswith("admin_select_topic_"):
                # Выбор темы для нового вопроса
                topic_id = int(query.data.replace("admin_select_topic_", ""))
                context.user_data["selected_topic_id"] = topic_id

                # Предлагаем выбрать тип вопроса
                reply_markup = admin_question_type_keyboard()

                await query.edit_message_text(
                    "Выберите тип вопроса:",
                    reply_markup=reply_markup
                )

            elif query.data.startswith("admin_question_type_"):
                # Выбор типа вопроса
                question_type = query.data.replace("admin_question_type_", "")
                context.user_data["question_type"] = question_type

                # Предлагаем ввести текст вопроса
                await query.edit_message_text(
                    "Отправьте текст вопроса в следующем сообщении."
                )

                # Обновляем состояние
                context.user_data["admin_state"] = "entering_question_text"

            elif query.data == "admin_question_analysis":
                await self.show_question_analysis(update, context)

            elif query.data == "admin_back_main":
                # Возврат в главное меню администратора
                await self.show_admin_panel(update, context)

            elif query.data == "admin_back_topics":
                # Возврат к списку тем
                with get_session() as session:
                    topics = session.query(Topic).all()
                    topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

                if not topics:
                    await query.edit_message_text(
                        "Сначала необходимо создать хотя бы одну тему. Используйте 'Редактировать темы'."
                    )
                    return

                # Используем готовую клавиатуру
                reply_markup = admin_topics_keyboard(topics_data)

                await query.edit_message_text(
                    "Выберите тему для нового вопроса:",
                    reply_markup=reply_markup
                )

            elif query.data == "admin_add_topic":
                # Добавление новой темы
                await query.edit_message_text(
                    "Отправьте название и описание новой темы в формате:\n\n"
                    "Название темы\n"
                    "Описание темы"
                )

                # Устанавливаем состояние для пользователя
                context.user_data["admin_state"] = "adding_topic"

            elif query.data.startswith("admin_edit_topic_"):
                # Редактирование выбранной темы
                topic_id = int(query.data.replace("admin_edit_topic_", ""))

                with get_session() as session:
                    topic = session.query(Topic).get(topic_id)

                    if not topic:
                        await query.edit_message_text(
                            "Тема не найдена."
                        )
                        return

                    # Используем готовую клавиатуру
                    reply_markup = admin_edit_topics_keyboard(topic_id)

                    await query.edit_message_text(
                        f"*Редактирование темы:* {topic.name}\n\n"
                        f"*Описание:* {topic.description or 'Нет описания'}\n\n"
                        "Выберите действие:",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )

            elif query.data == "admin_back_topics_list":
                # Возврат к списку тем
                await show_topics_list(update, context)

            # Обработчики для редактирования тем
            elif query.data.startswith("admin_edit_topics_desc_"):
                topic_id = int(query.data.replace("admin_edit_topics_desc_", ""))
                logger.info(f"Изменение описания темы с ID {topic_id}")
                await self.handle_topic_edit_action(update, context, "desc", topic_id)


            elif query.data.startswith("admin_delete_topic_"):
                topic_id = int(query.data.replace("admin_delete_topic_", ""))

                logger.info(f"Запрос на удаление темы с ID {topic_id}")

                with get_session() as session:
                    topic = session.query(Topic).get(topic_id)
                    if not topic:
                        await query.edit_message_text("Тема не найдена.")
                        return

                    # Проверяем, есть ли вопросы, связанные с этой темой
                    questions_count = session.query(Question).filter(Question.topic_id == topic_id).count()

                # Используем готовую клавиатуру для подтверждения
                reply_markup = admin_confirm_delete_keyboard(topic_id)

                warning_text = ""
                if questions_count > 0:
                    warning_text = f"\n⚠️ ВНИМАНИЕ! К этой теме привязано {questions_count} вопросов. При удалении темы все связанные вопросы также будут удалены."

                await query.edit_message_text(
                    f"Вы уверены, что хотите удалить тему '{topic.name}'?{warning_text}",
                    reply_markup=reply_markup
                )



            elif query.data.startswith("admin_confirm_delete_topic_"):
                topic_id = int(query.data.replace("admin_confirm_delete_topic_", ""))
                logger.info(f"Подтверждение удаления темы с ID {topic_id}")
                try:
                    topic_name = None
                    with get_session() as session:
                        topic = session.query(Topic).get(topic_id)
                        if not topic:
                            await query.edit_message_text("Тема не найдена.")
                            return
                        # Сохраняем имя темы до удаления
                        topic_name = topic.name
                        # Сначала удаляем все вопросы этой темы
                        session.query(Question).filter(Question.topic_id == topic_id).delete()
                        # Затем удаляем саму тему
                        session.delete(topic)
                        session.commit()
                    if topic_name:
                        await query.edit_message_text(f"✅ Тема '{topic_name}' и все связанные вопросы успешно удалены.")
                        # Пауза перед показом списка тем
                        await asyncio.sleep(2)
                        await show_topics_list(update, context)
                    else:
                        await query.edit_message_text("Тема успешно удалена.")
                        await show_topics_list(update, context)

                except Exception as e:
                    logger.error(f"Error deleting topic: {e}")
                    await query.edit_message_text(
                        f"Произошла ошибка при удалении темы: {str(e)}\n\n"
                        "Пожалуйста, попробуйте еще раз."
                    )

            # Обработчики для списков пользователей
            elif query.data == "admin_list_students":
                await self.show_students_list(update, context)

            elif query.data == "admin_list_parents":
                await self.show_parents_list(update, context)

            # Для просмотра конкретного ученика
            elif query.data.startswith("admin_view_student_"):
                student_id = int(query.data.replace("admin_view_student_", ""))
                await self.show_student_details(update, context, student_id)

            # Для просмотра конкретного родителя
            elif query.data.startswith("admin_view_parent_"):
                parent_id = int(query.data.replace("admin_view_parent_", ""))
                await self.show_parent_details(update, context, parent_id)

            # Для подтверждения удаления ученика
            elif query.data.startswith("admin_delete_student_"):
                student_id = int(query.data.replace("admin_delete_student_", ""))
                await self.confirm_delete_user(update, context, student_id, "student")

            # Для подтверждения удаления родителя
            elif query.data.startswith("admin_delete_parent_"):
                parent_id = int(query.data.replace("admin_delete_parent_", ""))
                await self.confirm_delete_user(update, context, parent_id, "parent")

            # Для выполнения удаления ученика
            elif query.data.startswith("admin_confirm_delete_student_"):
                student_id = int(query.data.replace("admin_confirm_delete_student_", ""))
                await self.delete_user(update, context, student_id, "student")

            # Для выполнения удаления родителя
            elif query.data.startswith("admin_confirm_delete_parent_"):
                parent_id = int(query.data.replace("admin_confirm_delete_parent_", ""))
                await self.delete_user(update, context, parent_id, "parent")


        except Exception as e:
            logger.error(f"Error in handle_admin_button: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при обработке запроса: {str(e)}"
            )

    async def handle_export_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE, export_type: str,
                                   period: str = None) -> None:
        """Обработка нажатий кнопок экспорта"""
        query = update.callback_query
        user_id = update.effective_user.id

        try:
            # Импортируем сервис экспорта
            from services.excel_export_service import ExcelExportService
            excel_service = ExcelExportService()

            # Показываем сообщение о генерации файла
            generating_msg = await query.edit_message_text("⏳ Генерация Excel-файла... Пожалуйста, подождите.")

            # Генерируем файл в зависимости от типа
            if export_type == "results":
                buffer = excel_service.export_test_results(period or "all")
                filename = f"test_results_{period or 'all'}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"
            elif export_type == "topics":
                buffer = excel_service.export_topic_statistics()
                filename = f"topic_statistics_{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"
            elif export_type == "students":
                buffer = excel_service.export_student_progress()
                filename = f"student_progress_{datetime.now(timezone.utc).strftime('%Y%m%d')}.xlsx"
            else:
                await query.edit_message_text("Неизвестный тип экспорта.")
                return

            # Удаляем сообщение о генерации
            await generating_msg.delete()

            # Отправляем файл пользователю
            await context.bot.send_document(
                chat_id=user_id,
                document=buffer,
                filename=filename,
                caption=f"📊 Экспорт данных: {export_type}\n{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M')}"
            )

        except Exception as e:
            logger.error(f"Error exporting to Excel: {e}")
            await query.edit_message_text(
                f"Произошла ошибка при экспорте: {str(e)}"
            )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик загрузки документов (для импорта вопросов)"""
        user_id = update.effective_user.id

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для импорта вопросов."
            )
            return

        # Проверяем, ожидается ли загрузка файла
        if context.user_data.get("admin_state") != "importing_questions":
            return

        # Проверяем тип документа
        document = update.message.document
        if not document.file_name.endswith('.json'):
            await update.message.reply_text(
                "Пожалуйста, загрузите файл в формате JSON."
            )
            return

        try:
            # Скачиваем файл
            file = await context.bot.get_file(document.file_id)
            file_path = f"downloads/{document.file_name}"
            os.makedirs("downloads", exist_ok=True)
            await file.download_to_drive(file_path)

            # Обрабатываем файл
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Импортируем вопросы
            result = self.import_questions_from_json(data)

            # Удаляем временный файл
            os.remove(file_path)

            if result["success"]:
                await update.message.reply_text(
                    f"✅ Импорт успешно завершен!\n\n"
                    f"• Добавлена тема: {result['topic_name']}\n"
                    f"• Импортировано вопросов: {result['questions_count']}"
                )
            else:
                await update.message.reply_text(
                    f"❌ Ошибка при импорте: {result['message']}"
                )

        except Exception as e:
            logger.error(f"Error importing questions: {e}")
            await update.message.reply_text(
                f"Произошла ошибка при обработке файла: {str(e)}"
            )

        # Сбрасываем состояние
        context.user_data.pop("admin_state", None)

    async def handle_admin_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, state=None) -> None:
        """Обработчик текстовых сообщений от администратора в процессе редактирования"""
        user_id = update.effective_user.id
        message_text = update.message.text

        # Проверяем, является ли пользователь администратором
        if str(user_id) not in ADMINS:
            await update.message.reply_text(
                "У вас нет прав для выполнения этой операции."
            )
            return

        # Проверяем состояние
        state = context.user_data.get("admin_state", None)
        logger.info(f"Обрабатываю состояние администратора: {state}")

        # Обработка состояний для редактирования тем
        if state == "editing_topic_name":
            topic_id = context.user_data.get("editing_topic_id")
            new_name = message_text.strip()

            if not new_name or len(new_name) < 3:
                await update.message.reply_text(
                    "Название темы должно содержать минимум 3 символа. Пожалуйста, попробуйте еще раз."
                )
                return

            try:
                with get_session() as session:
                    topic = session.query(Topic).get(topic_id)
                    if not topic:
                        await update.message.reply_text("Тема не найдена. Операция отменена.")
                        context.user_data.pop("admin_state", None)
                        context.user_data.pop("editing_topic_id", None)
                        return

                    old_name = topic.name
                    topic.name = new_name
                    session.commit()

                await update.message.reply_text(f"✅ Название темы успешно изменено с '{old_name}' на '{new_name}'.")

                # Сбрасываем состояние
                context.user_data.pop("admin_state", None)
                context.user_data.pop("editing_topic_id", None)

                # Создаем клавиатуру для просмотра тем
                with get_session() as session:
                    topics = session.query(Topic).all()
                    topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

                reply_markup = admin_edit_topics_keyboard(topics_data)

                # Отправляем сообщение со списком тем
                await update.message.reply_text(
                    "✏️ Список тем для редактирования:",
                    reply_markup=reply_markup
                )

            except Exception as e:
                logger.error(f"Error updating topic name: {e}")
                await update.message.reply_text(f"Произошла ошибка при изменении названия темы: {str(e)}")
                context.user_data.pop("admin_state", None)
                context.user_data.pop("editing_topic_id", None)

        elif state == "editing_topic_description":
            topic_id = context.user_data.get("editing_topic_id")
            new_description = message_text.strip()
            try:
                with get_session() as session:
                    topic = session.query(Topic).get(topic_id)
                    if not topic:
                        await update.message.reply_text("Тема не найдена. Операция отменена.")
                        context.user_data.pop("admin_state", None)
                        context.user_data.pop("editing_topic_id", None)
                        return

                    # Сохраняем название темы и старое описание, пока сессия активна
                    topic_name = topic.name
                    old_description = topic.description or "Нет описания"

                    # Обновляем описание
                    topic.description = new_description
                    session.commit()

                    logger.info(f"Описание темы {topic_id} успешно обновлено")

                await update.message.reply_text(
                    f"✅ Описание темы '{topic_name}' успешно обновлено."

                )
                # Сбрасываем состояние
                context.user_data.pop("admin_state", None)
                context.user_data.pop("editing_topic_id", None)

                # Создаем клавиатуру для просмотра тем
                with get_session() as session:
                    topics = session.query(Topic).all()
                    topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

                reply_markup = admin_edit_topics_keyboard(topics_data)
                # Отправляем сообщение со списком тем

                await update.message.reply_text(
                    "✏️ Список тем для редактирования:",
                    reply_markup=reply_markup

                )

            except Exception as e:
                logger.error(f"Error updating topic description: {e}")
                await update.message.reply_text(f"Произошла ошибка при изменении описания темы: {str(e)}")
                context.user_data.pop("admin_state", None)
                context.user_data.pop("editing_topic_id", None)


        # Добавляем остальные обработчики состояний
        elif state == "entering_question_text":
            # Сохраняем текст вопроса
            context.user_data["question_text"] = message_text

            # Запрашиваем варианты ответов
            await update.message.reply_text(
                "Отправьте варианты ответов, каждый с новой строки. Например:\n\n"
                "Вариант 1\n"
                "Вариант 2\n"
                "Вариант 3"
            )

            # Обновляем состояние
            context.user_data["admin_state"] = "entering_options"

        elif state == "entering_options":
            # Разбиваем сообщение на строки для получения вариантов
            options = [opt.strip() for opt in message_text.split('\n') if opt.strip()]

            if len(options) < 2:
                await update.message.reply_text(
                    "Необходимо указать минимум 2 варианта ответа. Пожалуйста, попробуйте еще раз."
                )
                return

            # Сохраняем варианты ответов
            context.user_data["options"] = options

            # Запрашиваем правильный ответ в зависимости от типа вопроса
            question_type = context.user_data.get("question_type", "single")

            if question_type == "single":
                # Показываем варианты ответов с номерами
                options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

                await update.message.reply_text(
                    f"Выберите номер правильного варианта ответа (от 1 до {len(options)}):\n\n{options_text}"
                )

                context.user_data["admin_state"] = "entering_correct_answer_single"

            elif question_type == "multiple":
                # Показываем варианты ответов с номерами
                options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

                await update.message.reply_text(
                    f"Укажите номера правильных вариантов ответов через запятую (например, 1,3,4):\n\n{options_text}"
                )

                context.user_data["admin_state"] = "entering_correct_answer_multiple"

            elif question_type == "sequence":
                # Показываем варианты ответов с номерами
                options_text = "\n".join([f"{i + 1}. {opt}" for i, opt in enumerate(options)])

                await update.message.reply_text(
                    f"Укажите правильную последовательность вариантов через запятую (например, 3,1,4,2):\n\n{options_text}"
                )

                context.user_data["admin_state"] = "entering_correct_answer_sequence"

        elif state == "entering_correct_answer_single":
            try:
                # Преобразуем ответ в индекс (с учетом, что нумерация начинается с 1)
                answer_index = int(message_text.strip()) - 1
                options = context.user_data.get("options", [])

                if answer_index < 0 or answer_index >= len(options):
                    await update.message.reply_text(
                        f"Указан неверный номер. Пожалуйста, выберите число от 1 до {len(options)}."
                    )
                    return

                # Сохраняем правильный ответ
                context.user_data["correct_answer"] = [answer_index]

                # Запрашиваем объяснение
                await update.message.reply_text(
                    "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
                )

                context.user_data["admin_state"] = "entering_explanation"

            except ValueError:
                await update.message.reply_text(
                    "Пожалуйста, введите число. Попробуйте еще раз."
                )

        elif state == "entering_correct_answer_multiple":
            try:
                # Разбиваем ответ на индексы
                answer_indices = [int(idx.strip()) - 1 for idx in message_text.split(',')]
                options = context.user_data.get("options", [])

                # Проверяем корректность индексов
                for idx in answer_indices:
                    if idx < 0 or idx >= len(options):
                        await update.message.reply_text(
                            f"Указан неверный номер: {idx + 1}. Пожалуйста, выберите числа от 1 до {len(options)}."
                        )
                        return

                # Сохраняем правильные ответы
                context.user_data["correct_answer"] = answer_indices

                # Запрашиваем объяснение
                await update.message.reply_text(
                    "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
                )

                context.user_data["admin_state"] = "entering_explanation"

            except ValueError:
                await update.message.reply_text(
                    "Пожалуйста, введите числа через запятую. Попробуйте еще раз."
                )

        elif state == "entering_correct_answer_sequence":
            try:
                # Разбиваем ответ на индексы
                sequence = [int(idx.strip()) - 1 for idx in message_text.split(',')]
                options = context.user_data.get("options", [])

                # Проверяем корректность индексов и их уникальность
                if len(sequence) != len(options) or len(set(sequence)) != len(options):
                    await update.message.reply_text(
                        f"Необходимо указать уникальные номера для всех {len(options)} вариантов."
                    )
                    return

                for idx in sequence:
                    if idx < 0 or idx >= len(options):
                        await update.message.reply_text(
                            f"Указан неверный номер: {idx + 1}. Пожалуйста, выберите числа от 1 до {len(options)}."
                        )
                        return

                # Преобразуем индексы в строки для единообразия с форматом хранения
                sequence_str = [str(idx) for idx in sequence]

                # Сохраняем правильную последовательность
                context.user_data["correct_answer"] = sequence_str

                # Запрашиваем объяснение
                await update.message.reply_text(
                    "Введите объяснение правильного ответа (или отправьте 'Нет' для пропуска этого шага):"
                )

                context.user_data["admin_state"] = "entering_explanation"

            except ValueError:
                await update.message.reply_text(
                    "Пожалуйста, введите числа через запятую. Попробуйте еще раз."
                )

        elif state == "entering_explanation":
            # Сохраняем объяснение, если оно не "Нет"
            explanation = None if message_text.lower() == "нет" else message_text

            # Собираем все данные для создания вопроса
            question_data = {
                "topic_id": context.user_data.get("selected_topic_id"),
                "text": context.user_data.get("question_text"),
                "options": context.user_data.get("options"),
                "correct_answer": context.user_data.get("correct_answer"),
                "question_type": context.user_data.get("question_type"),
                "explanation": explanation
            }

            # Создаем новый вопрос
            result = self.add_question_to_db(question_data)

            if result["success"]:
                await update.message.reply_text(
                    "✅ Вопрос успешно добавлен!"
                )

                # Спрашиваем, хочет ли администратор добавить еще один вопрос
                keyboard = [
                    [
                        InlineKeyboardButton("➕ Добавить еще вопрос", callback_data="admin_add_question"),
                        InlineKeyboardButton("🔙 Вернуться в меню", callback_data="admin_back_main")
                    ]
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)

                await update.message.reply_text(
                    "Выберите дальнейшее действие:",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    f"❌ Ошибка при добавлении вопроса: {result['message']}"
                )

            # Сбрасываем состояние
            context.user_data.pop("admin_state", None)

        elif state == "adding_topic":
            # Разбиваем сообщение на строки
            lines = message_text.strip().split('\n')

            if not lines:
                await update.message.reply_text(
                    "Пожалуйста, введите название темы."
                )
                return

            # Первая строка - название темы
            topic_name = lines[0].strip()

            # Остальные строки (если есть) - описание
            topic_description = '\n'.join(lines[1:]).strip() if len(lines) > 1 else None

            # Создаем новую тему
            result = self.add_topic_to_db(topic_name, topic_description)

            if result["success"]:
                await update.message.reply_text(
                    f"✅ Тема '{topic_name}' успешно добавлена!"
                )

                # Показываем обновленный список тем
                with get_session() as session:
                    topics = session.query(Topic).all()
                    topics_data = [{"id": topic.id, "name": topic.name} for topic in topics]

                reply_markup = admin_edit_topics_keyboard(topics_data)

                await update.message.reply_text(
                    "✏️ Список тем для редактирования:",
                    reply_markup=reply_markup
                )
            else:
                await update.message.reply_text(
                    f"❌ Ошибка при добавлении темы: {result['message']}"
                )

            # Сбрасываем состояние
            context.user_data.pop("admin_state", None)

        else:
            await update.message.reply_text(
                "Неизвестная команда. Пожалуйста, используйте панель администратора."
            )

    def import_questions_from_json(self, data: dict) -> dict:
        """Импорт вопросов из JSON"""
        try:
            # Проверяем структуру данных
            if "topic" not in data or "questions" not in data:
                return {"success": False, "message": "Неверная структура JSON. Должны быть поля 'topic' и 'questions'."}

            topic_data = data["topic"]
            questions_data = data["questions"]

            with get_session() as session:
                # Создаем или обновляем тему
                topic = session.query(Topic).filter(Topic.id == topic_data.get("id")).first()

                if not topic:
                    # Если темы с таким ID нет, создаем новую
                    topic = Topic(
                        name=topic_data["name"],
                        description=topic_data.get("description", "")
                    )
                    session.add(topic)
                    session.flush()  # Чтобы получить ID
                else:
                    # Если тема существует, обновляем её
                    topic.name = topic_data["name"]
                    topic.description = topic_data.get("description", topic.description)

                # Добавляем вопросы
                questions_count = 0
                for q_data in questions_data:
                    # Проверяем, существует ли уже вопрос с таким ID в этой теме
                    question = session.query(Question).filter(
                        Question.topic_id == topic.id,
                        Question.id == q_data.get("id")
                    ).first()

                    if not question:
                        # Создаем новый вопрос
                        options = q_data["options"]
                        correct_answer = q_data["correct_answer"]
                        question = Question(
                            topic_id=topic.id,
                            text=q_data["text"],
                            options=json.dumps(options) if not isinstance(options, str) else options,
                            correct_answer=json.dumps(correct_answer) if not isinstance(correct_answer,
                                                                                        str) else correct_answer,
                            question_type=q_data["question_type"],
                            difficulty=q_data.get("difficulty", 1),
                            media_url=q_data.get("media_url"),
                            explanation=q_data.get("explanation", "")
                        )
                        session.add(question)
                    else:
                        # Обновляем существующий вопрос
                        options = q_data["options"]
                        correct_answer = q_data["correct_answer"]
                        question.text = q_data["text"]
                        question.options = json.dumps(options) if not isinstance(options, str) else options
                        question.correct_answer = json.dumps(correct_answer) if not isinstance(correct_answer,
                                                                                               str) else correct_answer
                        question.question_type = q_data["question_type"]
                        question.difficulty = q_data.get("difficulty", question.difficulty)
                        question.media_url = q_data.get("media_url", question.media_url)
                        question.explanation = q_data.get("explanation", question.explanation)

                    questions_count += 1

                # Сохраняем изменения
                session.commit()

                return {
                    "success": True,
                    "topic_name": topic.name,
                    "questions_count": questions_count
                }

        except Exception as e:
            logger.error(f"Error in import_questions_from_json: {e}")
            return {"success": False, "message": str(e)}

    def add_question_to_db(self, data: dict) -> dict:
        """Добавление нового вопроса в базу данных"""
        try:
            # Проверяем наличие необходимых полей
            required_fields = ["topic_id", "text", "options", "correct_answer", "question_type"]
            for field in required_fields:
                if field not in data or data[field] is None:
                    return {"success": False, "message": f"Отсутствует обязательное поле: {field}"}

            with get_session() as session:
                try:
                    # Проверяем существование темы
                    topic = session.query(Topic).get(data["topic_id"])
                    if not topic:
                        return {"success": False, "message": "Указанная тема не существует"}

                    # Создаем новый вопрос
                    question = Question(
                        topic_id=data["topic_id"],
                        text=data["text"],
                        options=json.dumps(data["options"]) if not isinstance(data["options"], str) else data[
                            "options"],
                        correct_answer=json.dumps(data["correct_answer"]) if not isinstance(data["correct_answer"],
                                                                                            str) else data[
                            "correct_answer"],
                        question_type=data["question_type"],
                        difficulty=data.get("difficulty", 1),
                        media_url=data.get("media_url"),
                        explanation=data.get("explanation", "")
                    )

                    session.add(question)
                    session.commit()

                    return {"success": True, "question_id": question.id}
                except Exception as db_error:
                    session.rollback()
                    logger.error(f"Database error in add_question_to_db: {db_error}")
                    return {"success": False, "message": str(db_error)}

        except Exception as e:
            logger.error(f"Error in add_question_to_db: {e}")
            return {"success": False, "message": str(e)}

    def add_topic_to_db(self, name: str, description: str = None) -> dict:
        """Добавление новой темы в базу данных"""
        try:
            # Проверяем название
            if not name or len(name.strip()) < 3:
                return {"success": False, "message": "Название темы должно содержать минимум 3 символа"}

            with get_session() as session:
                # Проверяем уникальность названия
                existing_topic = session.query(Topic).filter(Topic.name == name).first()
                if existing_topic:
                    return {"success": False, "message": f"Тема с названием '{name}' уже существует"}

                # Создаем новую тему
                topic = Topic(
                    name=name,
                    description=description
                )

                session.add(topic)
                session.commit()

                return {"success": True, "topic_id": topic.id}

        except Exception as e:
            logger.error(f"Error in add_topic_to_db: {e}")
            return {"success": False, "message": str(e)}

    async def show_admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ панели администратора"""
        query = update.callback_query

        # Используем готовую клавиатуру
        reply_markup = admin_main_keyboard()

        await query.edit_message_text(
            "👨‍💻 *Панель администратора*\n\n"
            "Выберите действие из списка ниже:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    async def show_topic_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ статистики по темам"""
        query = update.callback_query

        # Получаем статистику по темам
        stats = generate_topic_analytics()

        if not stats["success"]:
            await query.edit_message_text(
                f"Ошибка получения статистики: {stats['message']}\n\n"
                "Нажмите /admin для возврата в панель администратора."
            )
            return

        if not stats["has_data"]:
            await query.edit_message_text(
                "Нет данных для анализа. Необходимо, чтобы ученики прошли хотя бы один тест.\n\n"
                "Нажмите /admin для возврата в панель администратора."
            )
            return

        try:
            # Форматируем текст со статистикой
            stats_text = "📊 *Статистика по темам*\n\n"

            # Добавляем информацию о самых сложных и простых темах
            topic_stats = stats["topic_stats"]
            stats_text += "*Сложность тем (от самой сложной к самой простой):*\n"

            for i, topic in enumerate(topic_stats):
                emoji = "🔴" if i < 2 else "🟡" if i < len(topic_stats) - 2 else "🟢"
                stats_text += f"{emoji} {topic['topic_name']}: {topic['avg_score']}% (пройдено тестов: {topic['tests_count']})\n"

            # Кнопка для возврата
            keyboard = [
                [InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")]
            ]

            reply_markup = InlineKeyboardMarkup(keyboard)

            # Отправляем текст статистики
            await query.edit_message_text(
                stats_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

            # Отправляем график
            if "chart" in stats:
                await context.bot.send_photo(
                    chat_id=update.effective_user.id,
                    photo=stats["chart"],
                    caption="📊 Средний результат по темам (от самых сложных к самым простым)"
                )
        except Exception as e:
            logger.error(f"Error in show_topic_stats: {e}")
            await query.edit_message_text(
                f"Произошла ошибка при отображении статистики: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def show_users_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ списка пользователей"""
        query = update.callback_query

        try:
            with get_session() as session:
                # Получаем статистику по пользователям
                students_count = session.query(User).filter(User.role == "student").count()
                parents_count = session.query(User).filter(User.role == "parent").count()
                admins_count = session.query(User).filter(User.role == "admin").count()

                # Получаем список последних активных пользователей
                # Важно: создаем копии данных, а не используем объекты сессии напрямую
                recent_users = []
                for user in session.query(User).order_by(User.last_active.desc()).limit(10).all():
                    recent_users.append({
                        "role": user.role,
                        "full_name": user.full_name,
                        "username": user.username,
                        "telegram_id": user.telegram_id,
                        "last_active": user.last_active
                    })

            # Форматируем текст со статистикой
            users_text = "👥 *Статистика пользователей*\n\n"
            users_text += f"• Всего учеников: {students_count}\n"
            users_text += f"• Всего родителей: {parents_count}\n"
            users_text += f"• Всего администраторов: {admins_count}\n\n"

            users_text += "*Недавняя активность:*\n"
            for user_data in recent_users:
                role_emoji = "👨‍🎓" if user_data["role"] == "student" else "👨‍👩‍👧‍👦" if user_data[
                                                                                           "role"] == "parent" else "👨‍💻"
                name = user_data["full_name"] or user_data["username"] or f"Пользователь {user_data['telegram_id']}"
                last_active = user_data["last_active"].strftime('%d.%m.%Y %H:%M')
                users_text += f"{role_emoji} {name} - {last_active}\n"

            # Используем готовую клавиатуру
            reply_markup = admin_users_keyboard()

            await query.edit_message_text(
                users_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Error in show_users_list: {e}")
            await query.edit_message_text(
                f"Произошла ошибка при получении списка пользователей: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def show_bot_settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ настроек бота"""
        query = update.callback_query

        from config import ENABLE_PARENT_REPORTS
        from services.settings_service import get_setting

        # Получаем настройки
        default_questions_count = get_setting("default_questions_count", "10")

        # Определяем время в зависимости от количества вопросов
        questions_count = int(default_questions_count)
        if questions_count <= 10:
            time_minutes = 5
        elif questions_count <= 15:
            time_minutes = 10
        else:
            time_minutes = 20

        # Форматируем текст с настройками
        settings_text = "⚙️ *Настройки бота*\n\n"
        settings_text += "Здесь вы можете настроить общие параметры работы бота:\n\n"

        settings_text += "*Текущие настройки:*\n"
        settings_text += f"• Автоматические отчеты родителям: {'Включено' if ENABLE_PARENT_REPORTS else 'Отключено'}\n"
        settings_text += f"• Количество вопросов в тесте: {default_questions_count}\n"
        settings_text += f"• Время на прохождение теста: {time_minutes} минут\n\n"

        settings_text += "Выберите настройку для изменения:"

        # Используем готовую клавиатуру
        reply_markup = admin_settings_keyboard()

        if query:
            await query.edit_message_text(
                settings_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                settings_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )

    async def show_students_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ списка учеников"""
        query = update.callback_query

        try:
            with get_session() as session:
                # Получаем список всех учеников
                students = session.query(User).filter(User.role == "student").order_by(User.last_active.desc()).all()

                if not students:
                    await query.edit_message_text(
                        "В базе данных нет зарегистрированных учеников.\n\n"
                        "Нажмите /admin для возврата в панель администратора."
                    )
                    return

                # Форматируем текст со списком учеников
                students_text = "👨‍🎓 *Список учеников*\n\n"
                students_text += "Выберите ученика для просмотра подробной информации и управления:\n\n"

                # Создаем клавиатуру с кнопками для каждого ученика
                keyboard = []
                for student in students:
                    name = student.full_name or student.username or f"Ученик {student.id}"
                    last_active = student.last_active.strftime('%d.%m.%Y') if student.last_active else "Никогда"

                    # Добавляем строку с информацией
                    students_text += f"• {name} (ID: {student.telegram_id})\n"
                    students_text += f"  Последняя активность: {last_active}\n\n"

                    # Добавляем кнопку для этого ученика
                    keyboard.append([
                        InlineKeyboardButton(f"🔍 {name}", callback_data=f"admin_view_student_{student.id}")
                    ])

                # Кнопка возврата
                keyboard.append([
                    InlineKeyboardButton("🔙 Назад к списку пользователей", callback_data="admin_users")
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # Проверяем, не слишком ли длинное сообщение
                if len(students_text) > 4096:
                    students_text = students_text[:4000] + "\n\n... (список обрезан)"

                await query.edit_message_text(
                    students_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in show_students_list: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении списка учеников: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

    async def show_parents_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Показ списка родителей"""
        query = update.callback_query

        try:
            with get_session() as session:
                # Получаем список всех родителей
                parents = session.query(User).filter(User.role == "parent").order_by(User.last_active.desc()).all()

                if not parents:
                    await query.edit_message_text(
                        "В базе данных нет зарегистрированных родителей.\n\n"
                        "Нажмите /admin для возврата в панель администратора."
                    )
                    return

                # Форматируем текст со списком родителей
                parents_text = "👨‍👩‍👧‍👦 *Список родителей*\n\n"
                parents_text += "Выберите родителя для просмотра подробной информации и управления:\n\n"

                # Создаем клавиатуру с кнопками для каждого родителя
                keyboard = []
                for parent in parents:
                    name = parent.full_name or parent.username or f"Родитель {parent.id}"
                    last_active = parent.last_active.strftime('%d.%m.%Y') if parent.last_active else "Никогда"

                    # Получаем связанных учеников
                    children_count = len(parent.children)

                    # Добавляем строку с информацией
                    parents_text += f"• {name} (ID: {parent.telegram_id})\n"
                    parents_text += f"  Последняя активность: {last_active}\n"
                    parents_text += f"  Связанных учеников: {children_count}\n\n"

                    # Добавляем кнопку для этого родителя
                    keyboard.append([
                        InlineKeyboardButton(f"🔍 {name}", callback_data=f"admin_view_parent_{parent.id}")
                    ])

                # Кнопка возврата
                keyboard.append([
                    InlineKeyboardButton("🔙 Назад к списку пользователей", callback_data="admin_users")
                ])

                reply_markup = InlineKeyboardMarkup(keyboard)

                # Проверяем, не слишком ли длинное сообщение
                if len(parents_text) > 4096:
                    parents_text = parents_text[:4000] + "\n\n... (список обрезан)"

                await query.edit_message_text(
                    parents_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Error in show_parents_list: {e}")
            logger.error(traceback.format_exc())
            await query.edit_message_text(
                f"Произошла ошибка при получении списка родителей: {str(e)}\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь к разработчику."
            )

        pass
