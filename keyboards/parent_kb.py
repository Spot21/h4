from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def parent_main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура для родителя"""
    keyboard = [
        [
            InlineKeyboardButton("🔗 Привязать ученика", callback_data="common_link_student"),
            InlineKeyboardButton("📊 Отчеты", callback_data="common_reports")
        ],
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data="common_parent_settings"),
            InlineKeyboardButton("🔍 Справка", callback_data="common_help")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def parent_students_keyboard(students) -> InlineKeyboardMarkup:
    """Клавиатура выбора ученика"""
    keyboard = []
    for student in students:
        name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
        keyboard.append([
            InlineKeyboardButton(
                name,
                callback_data=f"parent_student_{student['id']}"
            )
        ])
    return InlineKeyboardMarkup(keyboard)


def parent_notification_settings_keyboard(student_id: int, test_completion: bool,
                                        weekly_reports: bool, monthly_reports: bool) -> InlineKeyboardMarkup:
    """Клавиатура настроек уведомлений для родителя"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✅' if test_completion else '❌'} После прохождения теста",
                callback_data=f"parent_toggle_test_completion_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if weekly_reports else '❌'} Еженедельные отчеты",
                callback_data=f"parent_toggle_weekly_reports_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if monthly_reports else '❌'} Ежемесячные отчеты",
                callback_data=f"parent_toggle_monthly_reports_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Назад к списку учеников",
                callback_data="parent_back_students"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def parent_students_settings_keyboard(students) -> InlineKeyboardMarkup:
    """Клавиатура выбора ученика для настроек"""
    keyboard = []
    for student in students:
        name = student["full_name"] or student["username"] or f"Ученик {student['id']}"
        keyboard.append([
            InlineKeyboardButton(
                name,
                callback_data=f"parent_settings_{student['id']}"  # Используем другой префикс
            )
        ])
    return InlineKeyboardMarkup(keyboard)

def parent_report_period_keyboard(student_id) -> InlineKeyboardMarkup:
    """Клавиатура выбора периода для отчёта"""
    keyboard = [
        [
            InlineKeyboardButton("За неделю", callback_data=f"parent_report_{student_id}_week"),
            InlineKeyboardButton("За месяц", callback_data=f"parent_report_{student_id}_month")
        ],
        [
            InlineKeyboardButton("За год", callback_data=f"parent_report_{student_id}_year"),
            InlineKeyboardButton("Назад к списку учеников", callback_data="parent_back_students")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def parent_settings_keyboard(student_id, weekly_reports, test_completion,
                            low_score_threshold, high_score_threshold) -> InlineKeyboardMarkup:
    """Клавиатура настроек для ученика"""
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✅' if weekly_reports else '❌'} Еженедельные отчеты",
                callback_data=f"parent_toggle_weekly_reports_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✅' if test_completion else '❌'} Уведомления о тестах",
                callback_data=f"parent_toggle_test_completion_{student_id}"
            )
        ],
        [
            InlineKeyboardButton(
                f"Порог низкого результата: {low_score_threshold}%",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_none"
            )
        ],
        [
            InlineKeyboardButton(
                "▼",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_down"
            ),
            InlineKeyboardButton(
                "▲",
                callback_data=f"parent_threshold_low_score_threshold_{student_id}_up"
            )
        ],
        [
            InlineKeyboardButton(
                f"Порог высокого результата: {high_score_threshold}%",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_none"
            )
        ],
        [
            InlineKeyboardButton(
                "▼",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_down"
            ),
            InlineKeyboardButton(
                "▲",
                callback_data=f"parent_threshold_high_score_threshold_{student_id}_up"
            )
        ],
        [
            InlineKeyboardButton(
                "Назад к списку учеников",
                callback_data="parent_back_students"
            )
        ]
    ]
    return InlineKeyboardMarkup(keyboard)
