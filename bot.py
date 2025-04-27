import logging
import asyncio
import signal
import traceback
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, PicklePersistence
from telegram import Update
from config import BOT_TOKEN, ADMINS, DB_ENGINE
from telegram.ext import DictPersistence

from services.quiz_service import QuizService
from services.parent_service import ParentService

import handlers.start
from handlers.student import StudentHandler
from handlers.parent import ParentHandler
from handlers.admin import AdminHandler
from handlers.common import CommonHandler

from database.db_manager import init_db, get_session, engine
from services.notification import NotificationService

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)


class HistoryBot:
    def __init__(self, token):
        self.token = token
        self.application = None
        self.notification_service = None
        self.running = False

        # Сервисы
        self.quiz_service = None
        self.parent_service = None

        # Обработчики
        self.start_handler = None
        self.student_handler = None
        self.parent_handler = None
        self.admin_handler = None
        self.common_handler = None

    async def start(self):
        """Запуск бота"""
        try:
            # Инициализация базы данных
            init_db()

            # Инициализация сервисов
            self.quiz_service = QuizService()
            self.parent_service = ParentService()

            # Восстанавливаем состояние активных тестов
            self.quiz_service.restore_active_quizzes()

            # Создание экземпляра приложения
            persistence = DictPersistence()
            self.application = (
                Application.builder()
                .token(self.token)
                .read_timeout(30)
                .write_timeout(30)
                .connect_timeout(30)
                .pool_timeout(30)
                .persistence(persistence)
                .build()
            )

            # Инициализация обработчиков
            self._initialize_handlers()

            # Регистрация обработчиков команд
            self._register_handlers()

            # Инициализация сервиса уведомлений
            self.notification_service = NotificationService(self.application)
            await self.notification_service.start()

            # Установка обработчиков сигналов для корректного завершения
            self._setup_signal_handlers()

            # Запуск бота
            self.running = True
            await self.application.initialize()
            await self.application.start()
            logger.info("Bot started")

            # Запускаем polling и ждем завершения
            await self.application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )

            # Бесконечный цикл, чтобы бот работал до получения сигнала завершения
            while self.running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error during bot execution: {e}")
            logger.error(traceback.format_exc())
        finally:
            await self.shutdown()

    def _initialize_handlers(self):
        """Инициализация обработчиков"""
        # Создаем экземпляры обработчиков
        self.start_handler = handlers.start.StartHandler()
        self.student_handler = StudentHandler(self.quiz_service)
        self.parent_handler = ParentHandler(self.parent_service)
        self.admin_handler = AdminHandler()
        self.common_handler = CommonHandler(self.quiz_service, self.parent_service)

        # Инициализируем сервисы в обработчике администратора
        self.admin_handler.init_services(self.quiz_service, self.parent_service)

    def _register_handlers(self) -> None:
        """Регистрация обработчиков команд"""
        # Команды для всех пользователей
        self.application.add_handler(CommandHandler("start", self.start_handler.start_command))
        self.application.add_handler(CommandHandler("help", self.start_handler.help_command))
        self.application.add_handler(CommandHandler("mycode", self.start_handler.mycode_command))

        # Команды для учеников
        self.application.add_handler(CommandHandler("test", self.student_handler.start_test))
        self.application.add_handler(CommandHandler("stats", self.student_handler.show_stats))
        self.application.add_handler(CommandHandler("achievements", self.student_handler.show_achievements))

        # Команды для родителей
        self.application.add_handler(CommandHandler("link", self.parent_handler.link_student))
        self.application.add_handler(CommandHandler("report", self.parent_handler.get_report))
        self.application.add_handler(CommandHandler("settings", self.parent_handler.settings))

        # Команды для администраторов
        self.application.add_handler(CommandHandler("admin", self.admin_handler.admin_panel))
        self.application.add_handler(CommandHandler("add_question", self.admin_handler.add_question))
        self.application.add_handler(CommandHandler("import", self.admin_handler.import_questions))
        self.application.add_handler(CommandHandler("export_excel", self.admin_handler.export_to_excel))

        # Обработчики кнопок
        self.application.add_handler(CallbackQueryHandler(self.common_handler.handle_common_button, pattern="^common_"))
        self.application.add_handler(CallbackQueryHandler(self.student_handler.handle_test_button, pattern="^quiz_"))
        self.application.add_handler(CallbackQueryHandler(self.student_handler.handle_test_button, pattern="^student_"))
        self.application.add_handler(CallbackQueryHandler(self.parent_handler.handle_parent_button, pattern="^parent_"))


        # Проверяем наличие метода у админ обработчика
        if hasattr(self.admin_handler, 'handle_admin_button'):
            self.application.add_handler(
                CallbackQueryHandler(self.admin_handler.handle_admin_button, pattern="^admin_"))
        else:
            logger.error("AdminHandler doesn't have method 'handle_admin_button', skipping registration")

        # Обработка документов (для импорта вопросов)
        self.application.add_handler(MessageHandler(filters.Document.ALL, self.admin_handler.handle_document))

        # Обработчик остальных сообщений
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.common_handler.handle_message))

        # Обработчик ошибок
        self.application.add_error_handler(self.common_handler.error_handler)

    def _setup_signal_handlers(self):
        """Настройка обработчиков сигналов"""
        import platform
        if platform.system() != 'Windows':
            import signal
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self.shutdown(s.name))
                )

    async def shutdown(self, signal_name=None):
        """Корректное завершение работы бота"""
        if not self.running:
            return

        logger.info(f"Shutting down bot{f' (signal: {signal_name})' if signal_name else ''}")
        self.running = False

        try:
            # Сохраняем состояние активных тестов
            if self.quiz_service:
                try:
                    self.quiz_service.save_active_quizzes()
                    logger.info("Active quizzes state saved")
                except Exception as quiz_error:
                    logger.error(f"Error saving quiz state: {quiz_error}")

            if self.notification_service:
                await self.notification_service.stop()

            if self.application and self.application.updater.running:
                await self.application.updater.stop()

            if self.application:
                await self.application.stop()
                await self.application.shutdown()

            logger.info("Bot shutdown complete")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            logger.error(traceback.format_exc())


async def main():
    """Запуск бота"""
    bot = HistoryBot(BOT_TOKEN)
    await bot.start()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        logger.error(traceback.format_exc())