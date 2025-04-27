import json
import re
from typing import Dict, List, Any, Union, Tuple, Optional


def validate_question_data(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Проверка данных вопроса на корректность

    Args:
        data: Словарь с данными вопроса

    Returns:
        Tuple[bool, Optional[str]]: (Успех, Сообщение об ошибке)
    """
    # Проверяем наличие обязательных полей
    required_fields = ['text', 'options', 'correct_answer', 'question_type']
    for field in required_fields:
        if field not in data:
            return False, f"Отсутствует обязательное поле: {field}"

    # Проверяем тип вопроса
    valid_types = ['single', 'multiple', 'sequence']
    if data['question_type'] not in valid_types:
        return False, f"Недопустимый тип вопроса: {data['question_type']}. Допустимые типы: {', '.join(valid_types)}"

    # Проверяем варианты ответов
    options = data['options']
    if isinstance(options, str):
        try:
            options = json.loads(options)
        except json.JSONDecodeError:
            return False, "Невозможно преобразовать строку вариантов ответов в список"

    if not isinstance(options, list) or len(options) < 2:
        return False, "Варианты ответов должны быть списком с минимум 2 элементами"

    # Проверяем правильный ответ
    correct_answer = data['correct_answer']
    if isinstance(correct_answer, str):
        try:
            correct_answer = json.loads(correct_answer)
        except json.JSONDecodeError:
            return False, "Невозможно преобразовать строку правильного ответа в список или число"

    # Проверка для одиночного выбора
    if data['question_type'] == 'single':
        if not isinstance(correct_answer, list) or len(correct_answer) != 1:
            return False, "Для вопроса с одиночным выбором правильный ответ должен быть списком с одним элементом"

        answer_index = correct_answer[0]
        if not isinstance(answer_index, int) or answer_index < 0 or answer_index >= len(options):
            return False, f"Индекс правильного ответа должен быть числом от 0 до {len(options) - 1}"

    # Проверка для множественного выбора
    elif data['question_type'] == 'multiple':
        if not isinstance(correct_answer, list):
            return False, "Для вопроса с множественным выбором правильный ответ должен быть списком"

        if not correct_answer:
            return False, "Должен быть хотя бы один правильный вариант ответа"

        for answer_index in correct_answer:
            if not isinstance(answer_index, int) or answer_index < 0 or answer_index >= len(options):
                return False, f"Индекс правильного ответа должен быть числом от 0 до {len(options) - 1}"

    # Проверка для последовательности
    elif data['question_type'] == 'sequence':
        if not isinstance(correct_answer, list) or len(correct_answer) != len(options):
            return False, "Для вопроса с последовательностью правильный ответ должен быть списком той же длины, что и варианты"

        # Преобразуем все элементы в строки для единообразной проверки
        string_indices = [str(item) for item in correct_answer]

        # Проверяем уникальность
        if len(set(string_indices)) != len(options):
            return False, "Элементы последовательности должны быть уникальными"

        # Проверяем, что все индексы входят в допустимый диапазон
        valid_indices = set(str(i) for i in range(len(options)))
        if set(string_indices) != valid_indices:
            return False, f"Элементы последовательности должны быть числами от 0 до {len(options) - 1}"

    return True, None


def validate_topic_data(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Проверка данных темы на корректность

    Args:
        data: Словарь с данными темы

    Returns:
        Tuple[bool, Optional[str]]: (Успех, Сообщение об ошибке)
    """
    # Проверяем наличие обязательных полей
    if 'name' not in data:
        return False, "Отсутствует обязательное поле: name"

    # Проверяем длину названия
    if len(data['name']) < 3:
        return False, "Название темы должно содержать минимум 3 символа"

    if len(data['name']) > 100:
        return False, "Название темы не должно превышать 100 символов"

    return True, None


def validate_json_structure(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Проверка структуры JSON-файла с вопросами

    Args:
        data: Словарь с данными из JSON-файла

    Returns:
        Tuple[bool, Optional[str]]: (Успех, Сообщение об ошибке)
    """
    # Проверяем наличие обязательных разделов
    if 'topic' not in data:
        return False, "Отсутствует обязательный раздел: topic"

    if 'questions' not in data:
        return False, "Отсутствует обязательный раздел: questions"

    # Проверяем данные темы
    topic_valid, topic_error = validate_topic_data(data['topic'])
    if not topic_valid:
        return False, f"Ошибка в данных темы: {topic_error}"

    # Проверяем вопросы
    questions = data['questions']
    if not isinstance(questions, list) or not questions:
        return False, "Раздел questions должен быть непустым списком"

    for i, question in enumerate(questions):
        question_valid, question_error = validate_question_data(question)
        if not question_valid:
            return False, f"Ошибка в вопросе #{i + 1}: {question_error}"

    return True, None


def validate_parent_settings(settings: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Проверка настроек родительского контроля

    Args:
        settings: Словарь с настройками

    Returns:
        Tuple[bool, Optional[str]]: (Успех, Сообщение об ошибке)
    """
    # Проверяем пороговые значения
    if 'low_score_threshold' in settings:
        low_threshold = settings['low_score_threshold']
        if not isinstance(low_threshold, (int, float)) or low_threshold < 0 or low_threshold > 100:
            return False, "Порог низкого результата должен быть числом от 0 до 100"

    if 'high_score_threshold' in settings:
        high_threshold = settings['high_score_threshold']
        if not isinstance(high_threshold, (int, float)) or high_threshold < 0 or high_threshold > 100:
            return False, "Порог высокого результата должен быть числом от 0 до 100"

    # Проверяем, что порог низкого результата меньше порога высокого
    if 'low_score_threshold' in settings and 'high_score_threshold' in settings:
        if settings['low_score_threshold'] >= settings['high_score_threshold']:
            return False, "Порог низкого результата должен быть меньше порога высокого результата"

    return True, None


def validate_telegram_id(telegram_id: Union[str, int]) -> bool:
    """
    Проверка корректности Telegram ID

    Args:
        telegram_id: ID пользователя Telegram

    Returns:
        bool: True, если ID корректен
    """
    if isinstance(telegram_id, int):
        return telegram_id > 0

    if isinstance(telegram_id, str):
        return telegram_id.isdigit() and int(telegram_id) > 0

    return False


def validate_email(email: str) -> bool:
    """
    Проверка корректности email-адреса

    Args:
        email: Email-адрес для проверки

    Returns:
        bool: True, если email корректен
    """
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_pattern, email))