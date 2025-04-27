import json
from typing import Dict, List, Any
import markdown
import re


def format_question_text(question: Dict[str, Any], current_num: int, total_num: int) -> str:
    """
    Форматирование текста вопроса для отображения в сообщении бота

    Args:
        question: Словарь с данными вопроса
        current_num: Текущий номер вопроса
        total_num: Общее количество вопросов

    Returns:
        str: Отформатированный текст вопроса
    """
    text = f"*Вопрос {current_num}/{total_num}*\n\n"
    text += f"{question['text']}\n\n"

    # Добавляем варианты ответов, если они есть
    if 'options' in question:
        options = question['options']
        if isinstance(options, str):
            try:
                options = json.loads(options)
            except json.JSONDecodeError:
                options = []

        for i, option in enumerate(options):
            text += f"{chr(65 + i)}. {option}\n"

    # Добавляем информацию о типе вопроса
    if question.get('question_type') == 'multiple':
        text += "\n_Выберите все правильные варианты ответов_"
    elif question.get('question_type') == 'sequence':
        text += "\n_Расставьте варианты в правильном порядке_"

    return text


def safe_message_text(text: str, max_length: int = 4096, parse_mode: str = "Markdown") -> str:
    """
    Подготавливает текст сообщения для безопасной отправки в Telegram.

    Args:
        text: Исходный текст сообщения
        max_length: Максимальная длина сообщения Telegram
        parse_mode: Режим разметки (Markdown или HTML)

    Returns:
        str: Безопасный и правильно отформатированный текст
    """
    # Обрезаем текст, если он слишком длинный
    if len(text) > max_length:
        text = text[:max_length - 25] + "\n\n... (текст обрезан)"

    # Экранируем специальные символы в зависимости от режима разметки
    if parse_mode == "Markdown":
        # Экранируем спец. символы для Markdown
        escape_chars = r'_*[]()~`>#+-=|{}.!'
        for char in escape_chars:
            text = text.replace(char, f'\\{char}')

    return text

def format_test_results(result: Dict[str, Any]) -> str:
    """
    Форматирование результатов теста

    Args:
        result: Словарь с результатами теста

    Returns:
        str: Отформатированный текст с результатами
    """
    text = f"📊 *Результаты теста*\n\n"

    # Основная информация
    text += f"✅ Правильных ответов: {result['correct_count']} из {result['total_questions']}\n"
    text += f"📈 Процент успеха: {result['percentage']}%\n\n"

    # Эмодзи в зависимости от результата
    if result['percentage'] >= 90:
        text += "🏆 Отличный результат! Так держать! 🏆"
    elif result['percentage'] >= 70:
        text += "👍 Хороший результат! Продолжай в том же духе!"
    elif result['percentage'] >= 50:
        text += "💪 Неплохо, но есть куда расти!"
    else:
        text += "📚 Стоит повторить материал и попробовать еще раз."

    # Информация о новых достижениях
    if "new_achievements" in result and result["new_achievements"]:
        text += "\n\n🏅 *Новые достижения:*\n"
        for achievement in result["new_achievements"]:
            text += f"• {achievement['name']} - {achievement['description']} (+{achievement['points']} очков)\n"

    return text


def format_detailed_results(result: Dict[str, Any]) -> str:
    """
    Форматирование детальных результатов теста с объяснениями

    Args:
        result: Словарь с детальными результатами теста

    Returns:
        str: Отформатированный текст с детальными результатами
    """
    text = f"📋 *Детальный анализ результатов*\n\n"

    # Информация по каждому вопросу
    for i, q_result in enumerate(result['question_results']):
        is_correct = q_result['is_correct']

        text += f"*Вопрос {i + 1}*: {q_result['question']}\n"
        text += f"Ваш ответ: {format_answer(q_result['user_answer'], q_result.get('options', []))}\n"

        if not is_correct:
            text += f"Правильный ответ: {format_answer(q_result['correct_answer'], q_result.get('options', []))}\n"

        text += f"Результат: {'✅ Верно' if is_correct else '❌ Неверно'}\n"

        # Добавляем объяснение, если есть
        if q_result.get('explanation'):
            text += f"Объяснение: _{q_result['explanation']}_\n"

        text += "\n"

    return text


def format_answer(answer, options=None):
    """
    Форматирование ответа в читаемом виде

    Args:
        answer: Ответ пользователя (может быть числом, списком или строкой)
        options: Список вариантов ответов (если есть)

    Returns:
        str: Отформатированный ответ
    """
    if answer is None:
        return "Не отвечено"

    if isinstance(answer, list):
        if options and all(isinstance(a, int) for a in answer):
            # Если ответ - список индексов и есть варианты, преобразуем индексы в тексты
            return ", ".join([options[a] if a < len(options) else f"Вариант {a + 1}" for a in answer])
        else:
            return ", ".join(map(str, answer))

    if isinstance(answer, int) and options and answer < len(options):
        return options[answer]

    return str(answer)


def truncate_text(text: str, max_length: int = 4000) -> str:
    """
    Обрезает текст до указанной максимальной длины, добавляя "..." в конце

    Args:
        text: Исходный текст
        max_length: Максимальная длина текста

    Returns:
        str: Обрезанный текст
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - 3] + "..."


def escape_markdown(text: str) -> str:
    """
    Экранирует специальные символы в тексте для Markdown

    Args:
        text: Исходный текст

    Returns:
        str: Текст с экранированными символами
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)


def format_time_period(seconds: int) -> str:
    """
    Форматирует время в секундах в читаемый формат (часы, минуты, секунды)

    Args:
        seconds: Время в секундах

    Returns:
        str: Отформатированное время
    """
    if seconds < 60:
        return f"{seconds} сек"

    minutes = seconds // 60
    seconds %= 60

    if minutes < 60:
        return f"{minutes} мин {seconds} сек"

    hours = minutes // 60
    minutes %= 60

    return f"{hours} ч {minutes} мин {seconds} сек"