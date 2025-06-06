import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import ContextTypes
from datetime import datetime, timezone

from database.models import User
from database.db_manager import get_session
from config import ADMINS
from keyboards.student_kb import student_main_keyboard
from keyboards.parent_kb import parent_main_keyboard
from keyboards.admin_kb import admin_main_keyboard
from keyboards.menu_kb import student_main_menu, parent_main_menu, admin_main_menu, get_bot_commands

logger = logging.getLogger(__name__)

class StartHandler:
    def __init__(self):
        pass

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /start для начала работы с ботом"""

        user = update.effective_user
        user_id = user.id
        username = user.username
        full_name = f"{user.first_name} {user.last_name if user.last_name else ''}"

        # Определим роль пользователя (админ/родитель/ученик)
        role = "admin" if str(user_id) in ADMINS else None

        # Проверяем, существует ли пользователь в базе
        with get_session() as session:
            db_user = session.query(User).filter(User.telegram_id == user_id).first()

            if not db_user:
                # Если пользователь новый, предлагаем выбрать роль (если не админ)
                if role is None:
                    # Предлагаем выбрать роль
                    keyboard = [
                        [
                            InlineKeyboardButton("👨‍🎓 Я ученик", callback_data="common_role_student"),
                            InlineKeyboardButton("👨‍👩‍👧‍👦 Я родитель", callback_data="common_role_parent")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)

                    await update.message.reply_text(
                        f"Здравствуйте, {full_name}! 👋\n\n"
                        "Добро пожаловать в бот для проверки знаний по истории.\n\n"
                        "Пожалуйста, выберите, кем вы являетесь:",
                        reply_markup=reply_markup
                    )
                    return

                # Создаем нового пользователя
                new_user = User(
                    telegram_id=user_id,
                    username=username,
                    full_name=full_name,
                    role=role or "student",  # По умолчанию считаем ученика
                    created_at=datetime.now(timezone.utc),
                    last_active=datetime.now(timezone.utc)
                )
                session.add(new_user)
                session.commit()

                # Устанавливаем команды бота для роли пользователя
                from keyboards.menu_kb import set_commands_for_user
                await set_commands_for_user(update.get_bot(), user_id, role or "student")

                # Сообщаем о создании нового аккаунта
                if role == "admin":
                    # Отправляем сообщение и устанавливаем постоянную клавиатуру
                    await update.message.reply_text(
                        f"Здравствуйте, {full_name}! 👋\n\n"
                        "Вы зарегистрированы как администратор.\n"
                        "Используйте команду /admin для доступа к панели управления.",
                        reply_markup=admin_main_menu()
                    )
                else:
                    await update.message.reply_text(
                        f"Здравствуйте, {full_name}! 👋\n\n"
                        "Добро пожаловать в бот для проверки знаний по истории.\n"
                        "Ваш аккаунт успешно создан.",
                        reply_markup=student_main_menu()  # По умолчанию меню ученика
                    )
                    await self.show_main_menu(update, role or "student")
            else:
                # Обновляем информацию о пользователе
                db_user.username = username
                db_user.full_name = full_name
                db_user.last_active = datetime.now(timezone.utc)
                session.commit()

                # Устанавливаем команды бота для роли пользователя
                from keyboards.menu_kb import set_commands_for_user
                await set_commands_for_user(update.get_bot(), user_id, db_user.role)

                # Выбираем постоянную клавиатуру в зависимости от роли пользователя
                if db_user.role == "admin":
                    menu_keyboard = admin_main_menu()
                elif db_user.role == "parent":
                    menu_keyboard = parent_main_menu()
                else:
                    menu_keyboard = student_main_menu()

                # Приветствуем существующего пользователя
                if db_user.role == "admin":
                    await update.message.reply_text(
                        f"Здравствуйте, {full_name}! 👋\n\n"
                        "Вы авторизованы как администратор.\n"
                        "Используйте команду /admin для доступа к панели управления.",
                        reply_markup=menu_keyboard
                    )
                else:
                    await update.message.reply_text(
                        f"Здравствуйте, {full_name}! 👋\n\n"
                        "Рады видеть вас снова в боте для проверки знаний по истории.",
                        reply_markup=menu_keyboard
                    )
                    await self.show_main_menu(update, db_user.role)

    def get_help_text(self, role: str) -> str:
        """Возвращает текст справки в зависимости от роли пользователя"""
        if role == "student":
            return (
                "🔍 *Справка для ученика*\n\n"
                "*Основные команды:*\n"
                "• /start - Начать работу с ботом\n"
                "• /help - Показать эту справку\n"
                "• /test - Начать тестирование\n"
                "• /stats - Показать вашу статистику\n"
                "• /achievements - Показать ваши достижения\n"
                "• /mycode - Получить код для привязки родителя\n\n"
                "*Как проходить тесты:*\n"
                "1. Выберите тему с помощью команды /test\n"
                "2. Отвечайте на вопросы, выбирая варианты ответов\n"
                "3. После завершения теста вы получите результаты и объяснения\n\n"
                "*Система достижений:*\n"
                "Получайте баллы и достижения за правильные ответы и регулярное прохождение тестов!"
            )
        elif role == "parent":
            return (
                "🔍 *Справка для родителя*\n\n"
                "*Основные команды:*\n"
                "• /start - Начать работу с ботом\n"
                "• /help - Показать эту справку\n"
                "• /link - Привязать аккаунт ученика (требуется код)\n"
                "• /report - Получить отчет об успеваемости ученика\n"
                "• /settings - Настроить уведомления\n\n"
                "*Как привязать аккаунт ученика:*\n"
                "1. Попросите ученика выполнить команду /mycode\n"
                "2. Используйте команду /link с полученным кодом (например, /link 123456)\n"
                "3. После успешной привязки вы сможете получать отчеты и настраивать уведомления\n\n"
                "*Система уведомлений:*\n"
                "Настройте получение уведомлений о завершении тестов и еженедельных отчетов"
            )
        elif role == "admin":
            return (
                "🔍 *Справка для администратора*\n\n"
                "*Основные команды:*\n"
                "• /start - Начать работу с ботом\n"
                "• /help - Показать эту справку\n"
                "• /admin - Открыть панель администратора\n"
                "• /add_question - Добавить новый вопрос\n"
                "• /import - Импортировать вопросы из JSON файла\n"
                "• /export_excel - Экспортировать данные в Excel\n\n"
                "*Панель администратора позволяет:*\n"
                "• Управлять темами и вопросами\n"
                "• Просматривать статистику пользователей\n"
                "• Настраивать параметры бота\n"
                "• Анализировать проблемные вопросы\n"
                "• Отслеживать динамику результатов\n\n"
                "*Функции клавиатуры:*\n"
                "• 👨‍💻 Панель администратора - Основное меню администратора\n"
                "• 📊 Статистика - Статистика по темам\n"
                "• ➕ Добавить вопрос - Создание нового вопроса\n"
                "• 📁 Импорт вопросов - Импорт вопросов из JSON\n"
                "• 📤 Экспорт в Excel - Экспорт данных в Excel\n"
                "• ⚙️ Настройки - Настройки бота"
            )
        else:
            return (
                "Пожалуйста, используйте команду /start для начала работы с ботом"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /help для получения справки"""
        user_id = update.effective_user.id

        # Получаем роль пользователя
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()

            if not user:
                message = "Кажется, вы еще не зарегистрированы. Пожалуйста, используйте команду /start"
                if update.callback_query:
                    await update.callback_query.edit_message_text(message)
                else:
                    await update.message.reply_text(message)
                return

            # Получаем текст справки в зависимости от роли
            help_text = self.get_help_text(user.role)

            # Отправляем справку
            if update.callback_query:
                await update.callback_query.edit_message_text(
                    help_text,
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    help_text,
                    parse_mode="Markdown"
                )

    async def show_main_menu(self, update: Update, role: str) -> None:
        """Показывает основное меню в зависимости от роли пользователя"""
        user_id = update.effective_user.id

        # Инлайн-клавиатура для сообщения
        if role == "student":
            # Используем готовую инлайн-клавиатуру для ученика
            inline_markup = student_main_keyboard()
            # Постоянная клавиатура с кнопками
            reply_markup = student_main_menu()
        elif role == "parent":
            # Используем готовую инлайн-клавиатуру для родителя
            inline_markup = parent_main_keyboard()
            # Постоянная клавиатура с кнопками
            reply_markup = parent_main_menu()
        elif role == "admin":
            # Используем готовую инлайн-клавиатуру для администратора
            inline_markup = admin_main_keyboard()
            # Постоянная клавиатура с кнопками
            reply_markup = admin_main_menu()
        else:
            # Если роль неизвестна, используем клавиатуру ученика по умолчанию
            inline_markup = student_main_keyboard()
            reply_markup = student_main_menu()

        # Устанавливаем команды бота в зависимости от роли
        from keyboards.menu_kb import set_commands_for_user
        await set_commands_for_user(update.get_bot(), user_id, role)

        # Отправляем сообщение с инлайн-клавиатурой
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=inline_markup
        )

        # Отправляем сообщение с постоянной клавиатурой
        await update.message.reply_text(
            "Основное меню (всегда доступно):",
            reply_markup=reply_markup
        )

    async def mycode_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик команды /mycode для получения кода привязки родителя"""
        user_id = update.effective_user.id

        # Проверяем, что пользователь является учеником
        with get_session() as session:
            user = session.query(User).filter(User.telegram_id == user_id).first()

            if not user:
                await update.message.reply_text(
                    "Кажется, вы еще не зарегистрированы. Пожалуйста, используйте команду /start"
                )
                return

            if user.role != "student":
                await update.message.reply_text(
                    "Эта команда доступна только для учеников."
                )
                return

            # Код привязки - это telegram_id ученика
            code = str(user_id)

            await update.message.reply_text(
                f"📱 *Ваш код для привязки родителя:*\n\n"
                f"`{code}`\n\n"
                f"Передайте этот код родителю, чтобы он мог отслеживать вашу успеваемость.\n"
                f"Родитель должен использовать команду /link {code}",
                parse_mode="Markdown"
            )
