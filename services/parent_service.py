import json
import logging
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Dict, Any, Optional, Tuple
import traceback

from database.models import User, TestResult, Topic, Notification
from database.db_manager import get_session
from services.stats_service import get_user_stats

logger = logging.getLogger(__name__)


class ParentService:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ParentService, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if not self.initialized:

            self.initialized = True

    def link_student(self, parent_id: int, student_code: str) -> Dict[str, Any]:
        """Связывание аккаунта родителя с аккаунтом ученика по коду"""
        try:
            with get_session() as session:
                # Проверяем, что родитель существует
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                if parent.role != "parent":
                    return {"success": False, "message": "Только родители могут привязывать учеников"}

                # Проверяем, что ученик с таким кодом существует
                # Код пока примитивный - это просто строка с telegram_id ученика
                try:
                    student_telegram_id = int(student_code)
                except ValueError:
                    return {"success": False, "message": "Некорректный код ученика"}

                student = session.query(User).filter(User.telegram_id == student_telegram_id).first()
                if not student:
                    return {"success": False, "message": "Ученик с таким кодом не найден"}

                if student.role != "student":
                    return {"success": False, "message": "Указанный пользователь не является учеником"}

                # Проверяем, не привязан ли уже ученик к этому родителю
                student_exists = False
                for child in parent.children:
                    if child.id == student.id:
                        student_exists = True
                        break

                if student_exists:
                    return {"success": False, "message": "Этот ученик уже привязан к вашему аккаунту"}

                # Связываем аккаунты
                parent.children.append(student)
                session.commit()

                # После привязки ученика к родителю
                parent.children.append(student)

                # Создаем настройки уведомлений по умолчанию
                try:
                    parent_settings = json.loads(parent.settings) if parent.settings else {}
                except json.JSONDecodeError:
                    parent_settings = {}

                if "student_notifications" not in parent_settings:
                    parent_settings["student_notifications"] = {}

                # Устанавливаем настройки по умолчанию для этого ученика
                parent_settings["student_notifications"][str(student.id)] = {
                    "test_completion": True,  # Включаем уведомления о завершении тестов по умолчанию
                    "weekly_reports": False,
                    "monthly_reports": False,
                    "low_score_threshold": 60,
                    "high_score_threshold": 90
                }

                parent.settings = json.dumps(parent_settings)

                session.commit()

                student_name = student.full_name or student.username or student_telegram_id
                return {
                    "success": True,
                    "message": f"Ученик {student_name} успешно привязан к вашему аккаунту"
                }
        except Exception as e:
            logger.error(f"Error linking student: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": f"Произошла ошибка: {str(e)}"}

    def generate_detailed_report(self, parent_id: int, student_id: int, period: str = "week") -> Dict[str, Any]:
        """Генерация расширенного отчета с рекомендациями для родителя"""
        try:
            # Добавляем необходимые импорты
            from sqlalchemy import text, func

            with get_session() as session:
                # Проверяем, что родитель существует
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                # Проверяем, что ученик привязан к родителю
                student = None
                for child in parent.children:
                    if child.id == student_id:
                        student = child
                        break

                if not student:
                    return {"success": False, "message": "Ученик не найден среди привязанных учеников"}

                # Получаем расширенную статистику ученика
                from services.stats_service import get_extended_student_stats
                result = get_extended_student_stats(student.telegram_id, period)

                if not result["success"] or not result.get("has_data", False):
                    return result

                # Добавляем имя ученика в результат
                result["student_name"] = student.full_name or student.username or f"Ученик {student.id}"

                # Создаем сравнительный график с другими учениками
                comparison_chart = None
                try:
                    # Вариант 1: Используем ORM для построения запроса (более надежный способ)
                    students_data = session.query(
                        User.id.label('user_id'),
                        User.full_name.label('full_name'),
                        User.username.label('username'),
                        func.avg(TestResult.percentage).label('avg_score')
                    ).join(
                        TestResult, User.id == TestResult.user_id
                    ).filter(
                        User.role == 'student'
                    ).group_by(
                        User.id, User.full_name, User.username
                    ).order_by(
                        func.avg(TestResult.percentage).desc()
                    ).all()

                    # Если нужно использовать raw SQL через text(), то вариант 2:
                    """
                    query = text('''
                        SELECT 
                            u.id AS user_id,
                            u.full_name AS full_name,
                            u.username AS username,
                            AVG(tr.percentage) AS avg_score
                        FROM 
                            users u
                        JOIN
                            test_results tr ON u.id = tr.user_id
                        WHERE 
                            u.role = 'student'
                        GROUP BY 
                            u.id, u.full_name, u.username
                        ORDER BY 
                            avg_score DESC
                    ''')

                    students_data = session.execute(query).fetchall()
                    """

                    # Если есть результаты, создаем график
                    if students_data:
                        import matplotlib.pyplot as plt
                        from io import BytesIO

                        # Создаем данные для графика
                        student_names = []
                        student_scores = []
                        student_colors = []

                        # Ограничиваем количество учеников на графике
                        display_limit = 10
                        students_to_display = students_data[:display_limit]

                        for s in students_to_display:
                            # Безопасное извлечение данных из результата запроса
                            try:
                                name = s.full_name or s.username or f"Ученик #{s.user_id}"
                                name = name[:15] + "..." if len(name) > 15 else name
                                student_names.append(name)
                                student_scores.append(float(s.avg_score))  # Явное приведение к float

                                # Выделяем текущего ученика
                                if s.user_id == student.id:
                                    student_colors.append('red')
                                else:
                                    student_colors.append('blue')
                            except (AttributeError, TypeError) as e:
                                logger.warning(f"Error processing student data: {e}")
                                continue

                        # Если после обработки остались данные
                        if student_names and student_scores:
                            # Создаем график
                            plt.figure(figsize=(10, 6))
                            bars = plt.bar(student_names, student_scores, color=student_colors)

                            # Добавляем значения над столбцами
                            for bar in bars:
                                height = bar.get_height()
                                plt.text(
                                    bar.get_x() + bar.get_width() / 2.,
                                    height + 1,
                                    f'{height:.1f}%',
                                    ha='center',
                                    va='bottom'
                                )

                            plt.ylim(0, 105)  # Чтобы поместились значения над столбцами
                            plt.title("Сравнение успеваемости учеников")
                            plt.ylabel("Средний результат (%)")
                            plt.xlabel("Ученики")
                            plt.xticks(rotation=45, ha='right')
                            plt.tight_layout()

                            # Сохраняем график в буфер
                            img_buf = BytesIO()
                            plt.savefig(img_buf, format='png')
                            img_buf.seek(0)
                            plt.close()  # Закрываем фигуру

                            comparison_chart = img_buf

                            # Добавляем позицию ученика в рейтинге
                            student_position = None
                            for i, s in enumerate(students_data, 1):
                                if s.user_id == student.id:
                                    student_position = i
                                    break

                            if student_position:
                                result["rating_position"] = {
                                    "position": student_position,
                                    "total": len(students_data),
                                    "percentile": round(100 - (student_position - 1) * 100 / len(students_data), 1)
                                }
                except Exception as chart_error:
                    logger.error(f"Error creating comparison chart: {chart_error}")
                    logger.error(traceback.format_exc())

                # Добавляем график в результат, если он был создан
                if comparison_chart:
                    result["comparison_chart"] = comparison_chart

                return result

        except Exception as e:
            logger.error(f"Error generating detailed report: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": f"Произошла ошибка при создании отчета: {str(e)}"}

    def get_linked_students(self, parent_id: int) -> Dict[str, Any]:
        """Получение списка привязанных учеников"""
        try:
            with get_session() as session:
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                students = []
                for student in parent.children:
                    students.append({
                        "id": student.id,
                        "telegram_id": student.telegram_id,
                        "username": student.username,
                        "full_name": student.full_name
                    })

                return {"success": True, "students": students}
        except Exception as e:
            logger.error(f"Error getting linked students: {e}")
            return {"success": False, "message": f"Произошла ошибка: {str(e)}"}

    def generate_student_report(self, parent_id: int, student_id: int, period: str = "week") -> Dict[str, Any]:
        """Генерация отчета о прогрессе ученика за указанный период"""
        try:
            with get_session() as session:
                # Проверяем, что родитель существует
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                # Проверяем, что ученик привязан к родителю
                student = None
                for child in parent.children:
                    if child.id == student_id:
                        student = child
                        break

                if not student:
                    return {"success": False, "message": "Ученик не найден среди привязанных учеников"}

                # Определяем временной интервал для отчета
                now = datetime.utcnow()
                if period == "week":
                    start_date = now - timedelta(days=7)
                elif period == "month":
                    start_date = now - timedelta(days=30)
                elif period == "year":
                    start_date = now - timedelta(days=365)
                else:
                    start_date = now - timedelta(days=7)  # По умолчанию - неделя

                # Получаем результаты тестов ученика за указанный период
                test_results = (
                    session.query(TestResult)
                    .filter(TestResult.user_id == student.id)
                    .filter(TestResult.completed_at >= start_date)
                    .order_by(TestResult.completed_at)
                    .all()
                )

                if not test_results:
                    return {
                        "success": True,
                        "message": f"За выбранный период ({period}) ученик не проходил тесты",
                        "has_data": False,
                        "student_name": student.full_name or student.username
                    }

                # Собираем данные для отчета
                topics = {topic.id: topic.name for topic in session.query(Topic).all()}

                # Преобразуем результаты в DataFrame для анализа
                df = pd.DataFrame([
                    {
                        "date": result.completed_at,
                        "topic_id": result.topic_id,
                        "topic_name": topics.get(result.topic_id, f"Тема {result.topic_id}"),
                        "score": result.score,
                        "max_score": result.max_score,
                        "percentage": result.percentage,
                        "time_spent": result.time_spent
                    }
                    for result in test_results
                ])

                # Создаем график успеваемости
                fig = plt.figure(figsize=(10, 6))
                for topic_id, group in df.groupby("topic_id"):
                    plt.plot(
                        group["date"],
                        group["percentage"],
                        "o-",
                        label=group["topic_name"].iloc[0]
                    )

                plt.title(f"Успеваемость ученика {student.full_name or student.username}")
                plt.xlabel("Дата")
                plt.ylabel("Процент правильных ответов")
                plt.grid(True)
                plt.xticks(rotation=45)
                plt.tight_layout()

                if len(df["topic_id"].unique()) > 1:
                    plt.legend()

                # Сохраняем график в буфер
                img_buf = BytesIO()
                plt.savefig(img_buf, format='png')
                img_buf.seek(0)
                plt.close(fig)  # Закрываем конкретную фигуру

                # Статистика
                stats = {
                    "total_tests": len(test_results),
                    "average_score": round(df["percentage"].mean(), 1),
                    "best_result": {
                        "score": round(df["percentage"].max(), 1),
                        "topic": df.loc[df["percentage"].idxmax(), "topic_name"],
                        "date": df.loc[df["percentage"].idxmax(), "date"].strftime("%d.%m.%Y")
                    },
                    "worst_result": {
                        "score": round(df["percentage"].min(), 1),
                        "topic": df.loc[df["percentage"].idxmin(), "topic_name"],
                        "date": df.loc[df["percentage"].idxmin(), "date"].strftime("%d.%m.%Y")
                    },
                    "topics_studied": df["topic_name"].unique().tolist(),
                    "total_time_spent": df["time_spent"].sum() // 60  # В минутах
                }

                return {
                    "success": True,
                    "has_data": True,
                    "student_name": student.full_name or student.username,
                    "period": period,
                    "stats": stats,
                    "chart": img_buf
                }

        except Exception as e:
            logger.error(f"Error generating student report: {e}")
            logger.error(traceback.format_exc())
            return {"success": False, "message": f"Произошла ошибка при создании отчета: {str(e)}"}

    def setup_notifications(self, parent_id: int, student_id: int, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Настройка уведомлений для родителя о прогрессе ученика"""
        try:
            with get_session() as session:
                # Проверяем, что родитель существует
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                # Проверяем, что ученик привязан к родителю
                student = None
                for child in parent.children:
                    if child.id == student_id:
                        student = child
                        break

                if not student:
                    return {"success": False, "message": "Ученик не найден среди привязанных учеников"}

                # Обновляем настройки уведомлений
                try:
                    parent_settings = json.loads(parent.settings) if parent.settings else {}
                except json.JSONDecodeError:
                    logger.warning(f"Invalid settings JSON for user {parent_id}, resetting settings")
                    parent_settings = {}

                # Обеспечиваем правильную структуру настроек
                if not isinstance(parent_settings, dict):
                    parent_settings = {}

                # Если нет настроек для студентов, создаем их
                if "student_notifications" not in parent_settings:
                    parent_settings["student_notifications"] = {}

                # Если это не словарь, исправляем
                if not isinstance(parent_settings["student_notifications"], dict):
                    parent_settings["student_notifications"] = {}

                # Обновляем настройки для указанного ученика
                parent_settings["student_notifications"][str(student.id)] = settings

                # Сохраняем настройки
                parent.settings = json.dumps(parent_settings)
                session.commit()

                return {
                    "success": True,
                    "message": "Настройки уведомлений успешно обновлены"
                }

        except Exception as e:
            logger.error(f"Error setting up notifications: {e}")
            return {"success": False, "message": f"Произошла ошибка: {str(e)}"}

    def send_scheduled_reports(self) -> None:
        """Отправка запланированных отчетов родителям"""
        try:
            with get_session() as session:
                # Получаем всех родителей с настройками уведомлений
                parents = session.query(User).filter(User.role == "parent").all()

                for parent in parents:
                    # Пропускаем родителей без настроек
                    if not parent.settings:
                        continue

                    settings = json.loads(parent.settings)
                    if "student_notifications" not in settings:
                        continue

                    # Проверяем настройки для каждого ученика
                    for student_id_str, notification_settings in settings["student_notifications"].items():
                        student_id = int(student_id_str)

                        # Пропускаем, если отключены еженедельные отчеты
                        if not notification_settings.get("weekly_reports", False):
                            continue

                        # Проверяем, нужно ли отправлять отчет сегодня (например, каждое воскресенье)
                        today = datetime.utcnow()
                        if today.weekday() != 6:  # 6 - воскресенье
                            continue

                        # Генерируем отчет
                        student = session.query(User).get(student_id)
                        if not student:
                            continue

                        # Создаем уведомление о новом отчете
                        notification = Notification(
                            user_id=parent.id,
                            title=f"Еженедельный отчет по ученику {student.full_name or student.username}",
                            message="Ваш еженедельный отчет об успеваемости ученика готов. Используйте команду /report для просмотра.",
                            notification_type="report",
                            scheduled_at=today
                        )
                        session.add(notification)

                session.commit()

        except Exception as e:
            logger.error(f"Error sending scheduled reports: {e}")

    def process_test_completion(self, student_id: int, test_result: Dict[str, Any]) -> None:
        """Обработка завершения теста учеником для уведомления родителей"""
        try:
            with get_session() as session:
                # Находим ученика
                student = session.query(User).get(student_id)
                if not student:
                    return

                # Находим родителей этого ученика
                parents = session.query(User).filter(
                    User.role == "parent",
                    User.children.any(id=student_id)
                ).all()

                if not parents:
                    return

                # Для каждого родителя проверяем настройки уведомлений
                for parent in parents:
                    if not parent.settings:
                        continue

                    settings = json.loads(parent.settings)
                    if "student_notifications" not in settings:
                        continue

                    student_notifications = settings.get("student_notifications", {})
                    if not isinstance(student_notifications, dict):
                        student_notifications = {}
                    student_settings = student_notifications.get(str(student_id), {})

                    # Проверяем, нужно ли отправлять уведомления о завершении тестов
                    if not student_settings.get("test_completion", False):
                        continue

                    # Проверяем пороговые значения
                    notify = False
                    message = ""

                    if test_result["percentage"] < student_settings.get("low_score_threshold", 60):
                        notify = True
                        message = f"Ваш ребенок получил низкий результат ({test_result['percentage']}%) в тесте."
                    elif test_result["percentage"] > student_settings.get("high_score_threshold", 90):
                        notify = True
                        message = f"Поздравляем! Ваш ребенок получил высокий результат ({test_result['percentage']}%) в тесте."

                    if notify:
                        # Создаем уведомление
                        notification = Notification(
                            user_id=parent.id,
                            title=f"Результат теста ученика {student.full_name or student.username}",
                            message=message,
                            notification_type="test_result"
                        )
                        session.add(notification)

                session.commit()

        except Exception as e:
            logger.error(f"Error processing test completion: {e}")

    def get_parent_settings(self, parent_id: int) -> Dict[str, Any]:
        """Получение текущих настроек родителя"""
        try:
            with get_session() as session:
                parent = session.query(User).filter(User.telegram_id == parent_id).first()
                if not parent:
                    return {"success": False, "message": "Аккаунт родителя не найден"}

                settings = {}
                if parent.settings:
                    try:
                        settings = json.loads(parent.settings)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in parent settings for user {parent_id}")
                        settings = {}

                return {"success": True, "settings": settings}

        except Exception as e:
            logger.error(f"Error getting parent settings: {e}")
            return {"success": False, "message": f"Произошла ошибка: {str(e)}"}

    async def send_weekly_reports(self) -> None:
        """Отправка еженедельных отчетов родителям"""
        try:
            logger.info("Starting weekly reports generation")

            with get_session() as session:
                # Получаем всех родителей
                parents = session.query(User).filter(User.role == "parent").all()

                for parent in parents:
                    # Пропускаем родителей без настроек
                    if not parent.settings:
                        logger.info(f"Skipping parent {parent.id} - no settings")
                        continue

                    try:
                        settings = json.loads(parent.settings)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON in parent settings for user {parent.id}")
                        continue

                    # Пропускаем, если нет настроек уведомлений о детях
                    if "student_notifications" not in settings:
                        logger.info(f"Skipping parent {parent.id} - no student notifications")
                        continue

                    # Обходим всех учеников родителя
                    for student_id_str, student_settings in settings["student_notifications"].items():
                        # Пропускаем, если отключены еженедельные отчеты
                        if not student_settings.get("weekly_reports", False):
                            logger.info(f"Skipping reports for student {student_id_str} - weekly reports disabled")
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

                            # Проверяем, что ученик действительно является учеником
                            if student.role != "student":
                                logger.warning(f"User {student_id} is not a student")
                                continue

                            # Создаем уведомление о новом отчете
                            notification = Notification(
                                user_id=parent.id,
                                title=f"Еженедельный отчет по ученику {student.full_name or student.username}",
                                message="Ваш еженедельный отчет об успеваемости ученика готов. Используйте команду /report для просмотра.",
                                notification_type="report",
                                scheduled_at=datetime.utcnow()
                            )
                            session.add(notification)
                            logger.info(
                                f"Weekly report notification created for parent {parent.id}, student {student_id}")
                        except ValueError:
                            logger.error(f"Invalid student ID format: {student_id_str}")
                        except Exception as e:
                            logger.error(
                                f"Error generating weekly report notification for student {student_id_str}: {e}")
                            logger.error(traceback.format_exc())

                    # Сохраняем изменения
                    session.commit()

                logger.info("Weekly reports generation completed")
        except Exception as e:
            logger.error(f"Error sending weekly reports: {e}")
            logger.error(traceback.format_exc())


