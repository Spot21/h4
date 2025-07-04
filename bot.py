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
        self._shutdown_event = None

        # Сервисы
        self.quiz_service = None
        self.parent_service = None

        # Обработчики
        self.start_handler = None
        self.student_handler = None
        self.parent_handler = None
        self.admin_handler = None
        self.common_handler = None

        # Добавим словарь для быстрого доступа к обработчикам
        self.handlers = {}

    async def start(self):
        """Запуск бота"""
        try:
            # Инициализация базы данных
            init_db()

            # создаем экземпляр приложения
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

            # Инициализация сервисов
            self.quiz_service = QuizService()
            self.parent_service = ParentService()
            if self.quiz_service is None:
                logger.error("КРИТИЧЕСКАЯ ОШИБКА: quiz_service не инициализирован!")
                raise Exception("Не удалось инициализировать quiz_service")
            else:
                logger.info("quiz_service успешно инициализирован")

            # создаем сервис уведомлений с готовым application
            self.notification_service = NotificationService(self.application)

            # Передаем сервис уведомлений в quiz_service
            self.quiz_service.notification_service = self.notification_service

            # Инициализация обработчиков
            self._initialize_handlers()

            # Сохраняем ссылки в контексте приложения
            self.application.bot_data["handlers"] = self.handlers
            self.application.bot_data["quiz_service"] = self.quiz_service  # Добавляем для доступа


            # Восстанавливаем состояние активных тестов
            self.quiz_service.restore_active_quizzes()
            # Запускаем сервисы асинхронно
            await self.quiz_service.start()
            logger.info("quiz_service запущен")

            # Запускаем автосохранение
            await self.quiz_service.start_auto_save()

            # Регистрация обработчиков команд
            self._register_handlers()

            # Установка обработчиков сигналов для корректного завершения
            self._setup_signal_handlers()

            # Инициализация команд бота по умолчанию
            await self._setup_default_commands()

            # Запуск сервиса уведомлений ПОСЛЕ всех инициализаций
            await self.notification_service.start()

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

            # Используем Event для управления жизненным циклом вместо цикла со sleep
            self._shutdown_event = asyncio.Event()
            await self._shutdown_event.wait()

        except Exception as e:
            logger.error(f"Error during bot execution: {e}")
            logger.error(traceback.format_exc())
        finally:
            await self.shutdown()

    async def _setup_default_commands(self):
        """Настройка стандартных команд бота"""
        try:
            from keyboards.menu_kb import setup_default_commands

            # Устанавливаем базовый набор команд для всех пользователей
            success = await setup_default_commands(self.application.bot)

            if success:
                logger.info("Установлены стандартные команды бота")
            else:
                logger.warning("Не удалось установить стандартные команды бота")
        except Exception as e:
            logger.error(f"Ошибка при установке стандартных команд бота: {e}")
            logger.error(traceback.format_exc())

    def _initialize_handlers(self):
        """Инициализация обработчиков"""
        # Создаем экземпляры обработчиков
        self.start_handler = handlers.start.StartHandler()
        self.student_handler = StudentHandler(self.quiz_service)
        self.parent_handler = ParentHandler(self.parent_service)
        self.admin_handler = AdminHandler()

        # Инициализируем сервисы в обработчике администратора
        self.admin_handler.init_services(self.quiz_service, self.parent_service)

        # Создаем CommonHandler и передаем ему все остальные обработчики
        self.common_handler = CommonHandler(
            quiz_service=self.quiz_service,
            parent_service=self.parent_service,
            student_handler=self.student_handler,
            parent_handler=self.parent_handler,
            admin_handler=self.admin_handler,
            start_handler=self.start_handler
        )

        # Заполняем словарь обработчиков для удобного доступа
        self.handlers = {
            "start": self.start_handler,
            "student": self.student_handler,
            "parent": self.parent_handler,
            "admin": self.admin_handler,
            "common": self.common_handler
        }

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
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._handle_signal(s.name))
                )

    async def _handle_signal(self, signal_name):
        """Обработчик сигнала завершения"""
        logger.info(f"Получен сигнал {signal_name}, запускаем корректное завершение")
        await self.shutdown(signal_name)

    async def shutdown(self, signal_name=None):
        """Корректное завершение работы бота"""
        if not self.running:
            return

        logger.info(f"Shutting down bot{f' (signal: {signal_name})' if signal_name else ''}")
        self.running = False

        # Устанавливаем событие завершения
        if self._shutdown_event:
            self._shutdown_event.set()

        try:
            # Останавливаем автосохранение
            if self.quiz_service:
                await self.quiz_service.stop_auto_save()
                # Финальное сохранение
                self.quiz_service.save_active_quizzes()
                logger.info("Final quiz state saved")

            # Останавливаем уведомления
            if self.notification_service:
                await self.notification_service.stop()

            # Останавливаем polling
            if self.application and self.application.updater.running:
                await self.application.updater.stop()

            # Останавливаем application
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
