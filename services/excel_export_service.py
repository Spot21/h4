import pandas as pd
from io import BytesIO
from datetime import datetime, timedelta

from sqlalchemy import func, distinct

from database.models import User, TestResult, Topic, Question
from database.db_manager import get_session


class ExcelExportService:
    """Сервис для экспорта данных в Excel"""

    def export_test_results(self, period: str = "all") -> BytesIO:
        """Экспорт результатов тестов в Excel"""
        with get_session() as session:
            # Определяем временной интервал
            now = datetime.now()
            if period == "week":
                start_date = now - timedelta(days=7)
            elif period == "month":
                start_date = now - timedelta(days=30)
            elif period == "year":
                start_date = now - timedelta(days=365)
            else:
                start_date = datetime(1970, 1, 1)

            # Получаем результаты
            results = session.query(TestResult, User, Topic).join(
                User, TestResult.user_id == User.id
            ).join(
                Topic, TestResult.topic_id == Topic.id
            ).filter(
                TestResult.completed_at >= start_date
            ).all()

            # Формируем данные для Excel
            data = []
            for result, user, topic in results:
                data.append({
                    'ID ученика': user.telegram_id,
                    'Имя ученика': user.full_name or user.username,
                    'Класс': user.user_group or 'Не указан',  # Добавляем поле класса
                    'Тема': topic.name,
                    'Результат': f"{result.score}/{result.max_score}",
                    'Процент': result.percentage,
                    'Время (сек)': result.time_spent,
                    'Дата': result.completed_at.strftime('%d.%m.%Y %H:%M')
                })

            # Создаем DataFrame
            df = pd.DataFrame(data)

            # Экспортируем в Excel
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Результаты тестов', index=False)

                # Добавляем сводную статистику
                summary_df = pd.DataFrame({
                    'Всего тестов': [len(data)],
                    'Средний процент': [df['Процент'].mean() if len(df) > 0 else 0],
                    'Лучший результат': [df['Процент'].max() if len(df) > 0 else 0],
                    'Худший результат': [df['Процент'].min() if len(df) > 0 else 0]
                })
                summary_df.to_excel(writer, sheet_name='Сводка', index=False)

            buffer.seek(0)
            return buffer

    def export_topic_statistics(self) -> BytesIO:
        """Экспорт статистики по темам"""
        with get_session() as session:
            # Получаем статистику по темам
            topic_stats = session.query(
                Topic.name,
                func.count(TestResult.id).label('test_count'),
                func.avg(TestResult.percentage).label('avg_score'),
                func.count(distinct(TestResult.user_id)).label('student_count')
            ).join(
                TestResult, Topic.id == TestResult.topic_id
            ).group_by(
                Topic.id, Topic.name
            ).all()

            # Формируем данные для Excel
            data = []
            for stat in topic_stats:
                data.append({
                    'Тема': stat[0],
                    'Пройдено тестов': stat[1],
                    'Средний результат': round(stat[2], 1),
                    'Количество учеников': stat[3]
                })

            # Создаем DataFrame
            df = pd.DataFrame(data)

            # Экспортируем в Excel
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Статистика по темам', index=False)

            buffer.seek(0)
            return buffer

    def export_student_progress(self, student_id: int = None) -> BytesIO:
        """Экспорт прогресса учеников"""
        with get_session() as session:
            query = session.query(User, TestResult, Topic).join(
                TestResult, User.id == TestResult.user_id
            ).join(
                Topic, TestResult.topic_id == Topic.id
            ).filter(
                User.role == 'student'
            )

            if student_id:
                query = query.filter(User.id == student_id)

            results = query.order_by(User.id, TestResult.completed_at).all()

            # Формируем данные для Excel
            data = []
            current_student = None
            student_data = []

            for user, result, topic in results:
                if current_student != user.id:
                    if student_data:
                        # Добавляем данные предыдущего ученика
                        student_avg = sum(r['Процент'] for r in student_data) / len(student_data)
                        for row in student_data:
                            row['Средний результат ученика'] = round(student_avg, 1)
                            data.append(row)

                    current_student = user.id
                    student_data = []

                student_data.append({
                    'ID ученика': user.telegram_id,
                    'Имя ученика': user.full_name or user.username,
                    'Класс': user.user_group or 'Не указан',  # Добавляем поле класса
                    'Тема': topic.name,
                    'Результат': f"{result.score}/{result.max_score}",
                    'Процент': result.percentage,
                    'Дата': result.completed_at.strftime('%d.%m.%Y %H:%M')
                })

            # Добавляем данные последнего ученика
            if student_data:
                student_avg = sum(r['Процент'] for r in student_data) / len(student_data)
                for row in student_data:
                    row['Средний результат ученика'] = round(student_avg, 1)
                    data.append(row)

            # Создаем DataFrame
            df = pd.DataFrame(data)

            # Экспортируем в Excel
            buffer = BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='Прогресс учеников', index=False)

            buffer.seek(0)
            return buffer