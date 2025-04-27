import logging
import asyncio
import json
import traceback
from datetime import datetime, timedelta, timezone

import telegram
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from database.models import User, Notification
from database.db_manager import get_session
from services.parent_service import ParentService

logger = logging.getLogger(__name__)


class NotificationService:
    """Сервис для отправки уведомлений пользователям"""

    def __init__(self, application: Application):
        """Инициализация сервиса уведомлений"""
        self.application = application
        self.scheduler = None
        self._running = False
        self.parent_service = ParentService()

    # Изменения в services/notification.py

    async def start(self):
        """Запуск планировщика уведомлений"""
        try:
            if self._running:
                logger.warning("Notification service is already running")
                return

            # Создаем планировщик
            self.scheduler = AsyncIOScheduler()

            # Добавляем задачи с использованием асинхронных функций
            self.scheduler.add_job(
                self.process_notifications,
                'interval',
                minutes=2,
                id='process_notifications'
            )
            self.scheduler.add_job(
                self.send_weekly_reports,
                'cron',
                day_of_week='sun',
                hour=10,
                id='send_weekly_reports'
            )
            # Добавляем ежемесячные отчеты
            self.scheduler.add_job(
                self.send_monthly_reports,
                'cron',
                day=1,  # Первое число каждого месяца
                hour=10,
                id='send_monthly_reports'
            )
            self.scheduler.add_job(
                self.send_reminders,
                'cron',
                hour=18,
                id='send_reminders'
            )

            # Запускаем планировщик
            self.scheduler.start()
            self._running = True
            logger.info("Notification scheduler started")
        except Exception as e:
            logger.error(f"Error starting notification scheduler: {e}")
            logger.error(traceback.format_exc())
            self._running = False

    # В файле services/notification.py добавляем метод send_monthly_reports:

    async def send_monthly_reports(self):
        """Отправка ежемесячных отчетов родителям"""
        if not self._running:
            return

        try:
            logger.info("Starting monthly reports generation in NotificationService")
            with get_session() as session:
                # Получаем всех родителей
                parents = session.query(User).filter(User.role == "parent").all()

                for parent in parents:
                    # Пропускаем родителей без настроек
                    if not parent.settings:
                        continue

                    try:
                        settings = json.loads(parent.settings)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in parent settings for user {parent.id}")
                        continue

                    # Пропускаем, если нет настроек уведомлений о детях
                    if "student_notifications" not in settings:
                        continue

                    # Обходим всех учеников родителя
                    for student_id_str, student_settings in settings["student_notifications"].items():
                        # Пропускаем, если отключены ежемесячные отчеты
                        if not student_settings.get("monthly_reports", False):
                            continue

                        try:
                            student_id = int(student_id_str)

                            # Проверяем, что ученик существует и привязан к родителю
                            student = None
                            for child in parent.children:
                                if child.id == student_id:
                                    student = child
                                    break

                            if not student:
                                logger.warning(f"Student {student_id} not found in parent's children")
                                continue

                            # Создаем уведомление о новом отчете
                            notification = Notification(
                                user_id=parent.id,
                                title=f"Ежемесячный отчет по ученику {student.full_name or student.username}",
                                message="Ваш ежемесячный отчет об успеваемости ученика готов. Используйте команду /report для просмотра.",
                                notification_type="report",
                                scheduled_at=datetime.utcnow()
                            )
                            session.add(notification)
                            logger.info(
                                f"Monthly report notification created for parent {parent.id}, student {student_id}")
                        except ValueError:
                            logger.error(f"Invalid student ID format: {student_id_str}")
                        except Exception as e:
                            logger.error(
                                f"Error generating monthly report notification for student {student_id_str}: {e}")
                            logger.error(traceback.format_exc())

                    # Сохраняем изменения
                    session.commit()

            logger.info("Monthly reports generation completed in NotificationService")
        except Exception as e:
            logger.error(f"Error sending monthly reports: {e}")
            logger.error(traceback.format_exc())

    # обертки для асинхронных функций
    def _process_notifications_wrapper(self):
        asyncio.create_task(self.process_notifications())

    async def _send_weekly_reports_wrapper(self):
        asyncio.create_task(self.send_weekly_reports())

    def _send_reminders_wrapper(self):
        asyncio.create_task(self.send_reminders())

    async def stop(self):
        """Остановка планировщика уведомлений"""
        try:
            if self.scheduler and self._running:
                self.scheduler.shutdown(wait=True)  # Изменено на wait=True для более безопасного завершения
                self._running = False
                logger.info("Notification scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping notification scheduler: {e}")
            logger.error(traceback.format_exc())

    async def process_notifications(self):
        """Обработка и отправка запланированных уведомлений"""
        if not self._running:
            return

        try:
            logger.info("Запущена обработка уведомлений")
            processed_count = 0

            with get_session() as session:
                # Получаем все непрочитанные уведомления
                current_time = datetime.now(timezone.utc)
                notifications = session.query(Notification).filter(
                    Notification.is_read == False,
                    (Notification.scheduled_at <= current_time) |
                    (Notification.scheduled_at == None)
                ).all()

                logger.info(f"Найдено {len(notifications)} необработанных уведомлений")

                for notification in notifications:
                    # Получаем пользователя
                    user = session.query(User).get(notification.user_id)
                    if not user:
                        logger.warning(f"Пользователь не найден для уведомления {notification.id}")
                        notification.is_read = True
                        continue

                    # Отправляем уведомление
                    try:
                        await self.application.bot.send_message(
                            chat_id=user.telegram_id,
                            text=f"*{notification.title}*\n\n{notification.message}",
                            parse_mode="Markdown"
                        )

                        processed_count += 1

                        # Помечаем уведомление как прочитанное
                        notification.is_read = True
                        logger.info(f"Уведомление {notification.id} отправлено пользователю {user.telegram_id}")

                        # Если это уведомление об отчете, добавляем специальную кнопку
                        if notification.notification_type == "report":
                            keyboard = [
                                [
                                    InlineKeyboardButton("📊 Посмотреть отчет", callback_data="common_reports")
                                ]
                            ]
                            reply_markup = InlineKeyboardMarkup(keyboard)

                            await self.application.bot.send_message(
                                chat_id=user.telegram_id,
                                text="Вы можете посмотреть отчет, нажав на кнопку ниже:",
                                reply_markup=reply_markup
                            )

                    except telegram.error.BadRequest as bad_request:
                        logger.error(f"Ошибка при отправке уведомления {notification.id}: {bad_request}")
                        # Если ошибка не связана с форматированием, пытаемся отправить без разметки
                        if "can't parse entities" in str(bad_request).lower():
                            try:
                                await self.application.bot.send_message(
                                    chat_id=user.telegram_id,
                                    text=f"{notification.title}\n\n{notification.message}"
                                )
                                notification.is_read = True
                                processed_count += 1
                            except Exception as retry_error:
                                logger.error(f"Ошибка повторной отправки: {retry_error}")
                        else:
                            # Для других ошибок все равно отмечаем как прочитанное
                            notification.is_read = True

                    except telegram.error.Unauthorized:
                        logger.warning(f"Пользователь {user.telegram_id} заблокировал бота")
                        notification.is_read = True

                    except Exception as e:
                        logger.error(f"Ошибка отправки уведомления {notification.id}: {e}")
                        logger.error(traceback.format_exc())

                # Сохраняем изменения
                session.commit()
                logger.info(f"Обработка уведомлений завершена, отправлено {processed_count} из {len(notifications)}")

        except Exception as e:
            logger.error(f"Ошибка процесса обработки уведомлений: {e}")
            logger.error(traceback.format_exc())

    async def send_weekly_reports(self):
        """Отправка еженедельных отчетов родителям"""
        if not self._running:
            return

        try:
            logger.info("Starting weekly reports generation in NotificationService")
            await self.parent_service.send_weekly_reports()
            logger.info("Weekly reports generation completed in NotificationService")
        except Exception as e:
            logger.error(f"Error sending weekly reports: {e}")
            logger.error(traceback.format_exc())

    async def send_reminders(self):
        """Отправка напоминаний о необходимости пройти тест"""
        if not self._running:
            return

        try:
            with get_session() as session:
                # Получаем всех учеников, которые не проходили тест более недели
                week_ago = datetime.now() - timedelta(days=7)
                inactive_students = session.query(User).filter(
                    User.role == "student",
                    User.last_active < week_ago
                ).all()

                for student in inactive_students:
                    try:
                        await self.application.bot.send_message(
                            chat_id=student.telegram_id,
                            text="👋 Привет! Не забывай регулярно проверять свои знания по истории.\n"
                                 "Используй команду /test, чтобы начать тестирование."
                        )
                        logger.info(f"Reminder sent to student {student.telegram_id}")
                    except Exception as e:
                        logger.error(f"Error sending reminder to student {student.telegram_id}: {e}")
                        logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"Error sending reminders: {e}")
            logger.error(traceback.format_exc())

    async def create_notification(self, user_id: int, title: str, message: str,
                                  notification_type: str, scheduled_at: datetime = None) -> bool:
        """Создание нового уведомления"""
        try:
            with get_session() as session:
                # Проверяем существование пользователя
                user = session.query(User).get(user_id)
                if not user:
                    return False

                # Создаем уведомление
                notification = Notification(
                    user_id=user_id,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    scheduled_at=scheduled_at
                )
                session.add(notification)
                session.commit()

                # Если уведомление нужно отправить сейчас, запускаем обработку
                if scheduled_at is None or scheduled_at <= datetime.utcnow():
                    await self.process_notifications()

                return True

        except Exception as e:
            logger.error(f"Error creating notification: {e}")
            return False

    async def notify_test_completion(self, student_id: int, test_result: dict) -> None:
        """Уведомление родителей о завершении теста учеником"""
        try:
            # Получаем данные ученика
            with get_session() as session:
                student = session.query(User).get(student_id)
                if not student or student.role != "student":
                    logger.warning(f"Ученик {student_id} не найден или не является учеником")
                    return

                # Находим родителей этого ученика
                parents_query = (
                    session.query(User)
                    .filter(User.role == "parent")
                    .filter(User.children.any(id=student_id))
                )
                parents = parents_query.all()

                if not parents:
                    logger.info(f"Для ученика {student_id} не найдено родителей")
                    return

                # Определяем результат теста для сообщения
                percentage = test_result.get("percentage", 0)
                correct_count = test_result.get("correct_count", 0)
                total_questions = test_result.get("total_questions", 0)

                # Формируем текст уведомления
                if percentage >= 90:
                    result_description = "отличный результат"
                elif percentage >= 70:
                    result_description = "хороший результат"
                elif percentage >= 50:
                    result_description = "удовлетворительный результат"
                else:
                    result_description = "требуется дополнительная работа над материалом"

                message = (
                    f"Ученик {student.full_name or student.username} завершил тестирование.\n\n"
                    f"Результат: {correct_count} из {total_questions} правильных ответов ({percentage}%).\n"
                    f"Оценка: {result_description}.\n\n"
                    f"Для просмотра подробного отчета используйте команду /report."
                )

                # Для каждого родителя проверяем настройки уведомлений
                for parent in parents:
                    if not parent.settings:
                        logger.info(f"У родителя {parent.id} нет настроек уведомлений")
                        continue

                    try:
                        settings = json.loads(parent.settings)
                    except json.JSONDecodeError:
                        logger.warning(f"Ошибка формата JSON в настройках родителя {parent.id}")
                        continue

                    if "student_notifications" not in settings:
                        logger.info(f"У родителя {parent.id} нет настроек уведомлений для учеников")
                        continue

                    student_settings = settings["student_notifications"].get(str(student_id), {})

                    # Проверяем, нужно ли отправлять уведомление о завершении теста
                    if student_settings.get("test_completion", False):
                        # Получаем пороговые значения из настроек
                        low_threshold = student_settings.get("low_score_threshold", 60)
                        high_threshold = student_settings.get("high_score_threshold", 90)

                        # Проверяем пороговые значения для определения заголовка
                        if percentage < low_threshold:
                            title = "Низкий результат теста"
                        elif percentage >= high_threshold:
                            title = "Высокий результат теста"
                        else:
                            title = "Результат теста"

                        # Создаем уведомление для родителя
                        notification = Notification(
                            user_id=parent.id,
                            title=title,
                            message=message,
                            notification_type="test_result",
                            scheduled_at=datetime.now()  # Устанавливаем текущую дату
                        )
                        session.add(notification)
                        logger.info(
                            f"Создано уведомление о результате теста для родителя {parent.id}, ученик {student_id}, результат {percentage}%")

                # Сохраняем изменения
                session.commit()
                logger.info(f"Уведомления о результатах теста сохранены в базу данных")

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления о завершении теста: {e}")
            logger.error(traceback.format_exc())  # Для лучшей диагностики
