from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# keyboards/student_kb.py - изменение в student_main_keyboard
def student_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура для ученика"""
    keyboard = [
        [
            InlineKeyboardButton("📝 Начать тест", callback_data="common_start_test"),
            InlineKeyboardButton("📊 Моя статистика", callback_data="common_stats")
        ],
        [
            InlineKeyboardButton("🎯 Рекомендации", callback_data="student_recommendations"),
            InlineKeyboardButton("🏆 Достижения", callback_data="common_achievements")
        ],
        [
            InlineKeyboardButton("🔍 Справка", callback_data="common_help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def topic_selection_keyboard(topics) -> InlineKeyboardMarkup:
    """Клавиатура выбора темы для тестирования"""
    keyboard = []
    for topic in topics:
        keyboard.append([
            InlineKeyboardButton(
                topic["name"],
                callback_data=f"quiz_start_{topic['id']}"
            )
        ])

    # Добавляем кнопку случайной темы
    keyboard.append([
        InlineKeyboardButton(
            "🎲 Случайная тема",
            callback_data="quiz_start_random"
        )
    ])

    return InlineKeyboardMarkup(keyboard)


def single_question_keyboard(question_id, options) -> InlineKeyboardMarkup:
    """Клавиатура для вопроса с одиночным выбором"""
    keyboard = []
    for i, option in enumerate(options):
        keyboard.append([
            InlineKeyboardButton(option, callback_data=f"quiz_answer_{question_id}_{i}")
        ])

    # Кнопка пропуска
    keyboard.append([
        InlineKeyboardButton("⏩ Пропустить", callback_data="quiz_skip")
    ])

    return InlineKeyboardMarkup(keyboard)


def multiple_question_keyboard(question_id, options, selected_options=None) -> InlineKeyboardMarkup:
    """Клавиатура для вопроса с множественным выбором"""
    if selected_options is None:
        selected_options = []

    keyboard = []
    for i, option in enumerate(options):
        # Добавляем чекбоксы для выбранных вариантов
        is_selected = i in selected_options
        button_text = f"{'☑' if is_selected else '☐'} {option}"
        keyboard.append([
            InlineKeyboardButton(button_text, callback_data=f"quiz_answer_{question_id}_{i}")
        ])

    # Кнопка подтверждения и пропуска
    keyboard.append([
        InlineKeyboardButton("✅ Подтвердить выбор", callback_data=f"quiz_confirm_{question_id}")
    ])
    keyboard.append([
        InlineKeyboardButton("⏩ Пропустить", callback_data="quiz_skip")
    ])

    return InlineKeyboardMarkup(keyboard)


def sequence_question_keyboard(question_id, options, current_sequence=None) -> InlineKeyboardMarkup:
    keyboard = []

    # Убедимся, что current_sequence - всегда список
    if current_sequence is None:
        current_sequence = []

    # Проверяем именно длину списка
    if len(current_sequence) == 0:
        # Показываем все варианты для выбора
        for i, option in enumerate(options):
            keyboard.append([
                InlineKeyboardButton(f"{i + 1}. {option}", callback_data=f"quiz_seq_{question_id}_{i}")
            ])
    else:
        # Показываем оставшиеся варианты
        remaining_options = [i for i in range(len(options)) if str(i) not in current_sequence]
        for i in remaining_options:
            keyboard.append([
                InlineKeyboardButton(options[i], callback_data=f"quiz_seq_{question_id}_{i}")
            ])

        # Кнопки сброса и подтверждения
        keyboard.append([
            InlineKeyboardButton("🔄 Сбросить", callback_data=f"quiz_reset_{question_id}"),
            InlineKeyboardButton("✅ Подтвердить", callback_data=f"quiz_confirm_{question_id}")
        ])

    # Кнопка пропуска
    keyboard.append([
        InlineKeyboardButton("⏩ Пропустить", callback_data="quiz_skip")
    ])

    return InlineKeyboardMarkup(keyboard)


def test_results_keyboard(topic_id) -> InlineKeyboardMarkup:
    """Клавиатура после завершения теста"""
    keyboard = [
        [
            InlineKeyboardButton("📋 Детальный анализ", callback_data="quiz_details"),
            InlineKeyboardButton("🔄 Пройти еще раз", callback_data=f"quiz_repeat_{topic_id}")
        ],
        [
            InlineKeyboardButton("📊 Статистика", callback_data="common_stats"),
            InlineKeyboardButton("🏆 Достижения", callback_data="common_achievements")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def stats_period_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора периода для статистики"""
    keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data="common_stats_week"),
            InlineKeyboardButton("За месяц", callback_data="common_stats_month"),
            InlineKeyboardButton("За год", callback_data="common_stats_year"),
            InlineKeyboardButton("За всё время", callback_data="common_stats_all")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="common_back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def achievements_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для раздела достижений"""
    keyboard = [
        [
            InlineKeyboardButton("📊 Статистика", callback_data="common_stats"),
            InlineKeyboardButton("🏆 Таблица лидеров", callback_data="common_leaderboard")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="common_back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def leaderboard_period_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора периода для таблицы лидеров"""
    keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data="common_leaderboard_week"),
            InlineKeyboardButton("За месяц", callback_data="common_leaderboard_month")
        ],
        [
            InlineKeyboardButton("За год", callback_data="common_leaderboard_year"),
            InlineKeyboardButton("За всё время", callback_data="common_leaderboard_all")
        ],
        [
            InlineKeyboardButton("🔙 Назад к статистике", callback_data="common_stats"),
            InlineKeyboardButton("🏠 Главное меню", callback_data="common_back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)