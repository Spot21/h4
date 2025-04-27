from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# keyboards/admin_kb.py - изменение в admin_main_keyboard
# Обновить функцию admin_main_keyboard в keyboards/admin_kb.py

def admin_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура админ-панели"""
    keyboard = [
        [
            InlineKeyboardButton("📊 Статистика по темам", callback_data="admin_topic_stats"),
            InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
        ],
        [
            InlineKeyboardButton("🔴 Проблемные вопросы", callback_data="admin_problematic_questions"),
            InlineKeyboardButton("📈 Динамика результатов", callback_data="admin_results_dynamics")
        ],
        [
            InlineKeyboardButton("➕ Добавить вопрос", callback_data="admin_add_question"),
            InlineKeyboardButton("📁 Импорт вопросов", callback_data="admin_import")
        ],
        [
            InlineKeyboardButton("📤 Экспорт в Excel", callback_data="admin_export"),
            InlineKeyboardButton("✏️ Редактировать темы", callback_data="admin_edit_topics")
        ],
        [
            InlineKeyboardButton("⚙️ Настройки бота", callback_data="admin_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_topics_keyboard(topics) -> InlineKeyboardMarkup:
    """Клавиатура выбора темы для нового вопроса"""
    keyboard = []
    for topic in topics:
        keyboard.append([
            InlineKeyboardButton(
                topic["name"],
                callback_data=f"admin_select_topic_{topic['id']}"
            )
        ])

    # Добавляем кнопку возврата
    keyboard.append([
        InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
    ])

    return InlineKeyboardMarkup(keyboard)

def admin_question_type_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа вопроса"""
    keyboard = [
        [
            InlineKeyboardButton("Одиночный выбор", callback_data="admin_question_type_single"),
            InlineKeyboardButton("Множественный выбор", callback_data="admin_question_type_multiple")
        ],
        [
            InlineKeyboardButton("Последовательность", callback_data="admin_question_type_sequence"),
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_topics")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_edit_topics_keyboard(topics_or_id) -> InlineKeyboardMarkup:
    """Клавиатура для редактирования тем"""
    # Если передан ID темы
    if isinstance(topics_or_id, int):
        # Возвращаем клавиатуру для конкретной темы
        keyboard = [
            [
                InlineKeyboardButton("✏️ Изменить название", callback_data=f"admin_edit_topic_name_{topics_or_id}"),
                InlineKeyboardButton("📝 Изменить описание", callback_data=f"admin_edit_topic_desc_{topics_or_id}")
            ],
            [
                InlineKeyboardButton("❌ Удалить тему", callback_data=f"admin_delete_topic_{topics_or_id}"),
                InlineKeyboardButton("🔙 Назад", callback_data="admin_back_topics_list")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)

    # Иначе предполагаем, что передан список тем
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить тему", callback_data="admin_add_topic")
        ]
    ]

    # Добавляем кнопки для редактирования существующих тем
    for topic in topics_or_id:
        keyboard.append([
            InlineKeyboardButton(f"✏️ {topic['name']}", callback_data=f"admin_edit_topic_{topic['id']}")
        ])

    # Добавляем кнопку возврата
    keyboard.append([
        InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
    ])

    return InlineKeyboardMarkup(keyboard)

def admin_edit_topic_keyboard(topic_id) -> InlineKeyboardMarkup:
    """Клавиатура для конкретной темы"""
    keyboard = [
        [
            InlineKeyboardButton("✏️ Изменить название", callback_data=f"admin_edit_topic_name_{topic_id}"),
            InlineKeyboardButton("📝 Изменить описание", callback_data=f"admin_edit_topic_desc_{topic_id}")
        ],
        [
            InlineKeyboardButton("❌ Удалить тему", callback_data=f"admin_delete_topic_{topic_id}"),
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_topics_list")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_student_actions_keyboard(student_id) -> InlineKeyboardMarkup:
    """Клавиатура действий с конкретным учеником"""
    keyboard = [
        [
            InlineKeyboardButton("❌ Удалить ученика", callback_data=f"admin_delete_student_{student_id}")
        ],
        [
            InlineKeyboardButton("🔙 Назад к списку учеников", callback_data="admin_list_students")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_parent_actions_keyboard(parent_id) -> InlineKeyboardMarkup:
    """Клавиатура действий с конкретным родителем"""
    keyboard = [
        [
            InlineKeyboardButton("❌ Удалить родителя", callback_data=f"admin_delete_parent_{parent_id}")
        ],
        [
            InlineKeyboardButton("🔙 Назад к списку родителей", callback_data="admin_list_parents")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_confirm_delete_user_keyboard(user_id, user_type) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления пользователя"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"admin_confirm_delete_{user_type}_{user_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"admin_view_{user_type}_{user_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_settings_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настроек бота"""
    keyboard = [
        [
            InlineKeyboardButton("📊 Отчеты родителям", callback_data="admin_setting_reports")
        ],
        [
            InlineKeyboardButton("🔢 Количество вопросов", callback_data="admin_setting_questions_count")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_questions_count_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора количества вопросов"""
    keyboard = [
        [
            InlineKeyboardButton("5", callback_data="admin_set_questions_5"),
            InlineKeyboardButton("10", callback_data="admin_set_questions_10")
        ],
        [
            InlineKeyboardButton("15", callback_data="admin_set_questions_15"),
            InlineKeyboardButton("20", callback_data="admin_set_questions_20")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_reports_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура настройки отчетов родителям"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Включить", callback_data="admin_reports_enable"),
            InlineKeyboardButton("❌ Отключить", callback_data="admin_reports_disable")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="admin_settings")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_users_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для управления пользователями"""
    keyboard = [
        [
            InlineKeyboardButton("👨‍🎓 Ученики", callback_data="admin_list_students"),
            InlineKeyboardButton("👨‍👩‍👧‍👦 Родители", callback_data="admin_list_parents")
        ],
        [
            InlineKeyboardButton("🔙 Назад", callback_data="admin_back_main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def admin_confirm_delete_keyboard(topic_id) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления темы"""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, удалить", callback_data=f"admin_confirm_delete_topic_{topic_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"admin_edit_topic_{topic_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)