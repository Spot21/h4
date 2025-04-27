import os
import logging
import traceback
from typing import Optional, Tuple, Union
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

from config import MEDIA_DIR

logger = logging.getLogger(__name__)


def get_text_dimensions(draw, text, font):
    try:
        # Новый метод в PIL >= 9.2.0
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        except AttributeError:
            # Старый метод
            text_width, text_height = draw.textsize(text, font=font)

        return text_width, text_height
    except Exception as e:
        logger.error(f"Error calculating text dimensions: {e}")
        return 0, 0

    except Exception as e:
        logger.error(f"Error creating placeholder image: {e}")
        # Возвращаем пустой буфер в случае ошибки
        return BytesIO()

def ensure_media_directories() -> None:
    """Создание необходимых директорий для медиа-файлов"""
    try:
        os.makedirs(MEDIA_DIR, exist_ok=True)
        os.makedirs(os.path.join(MEDIA_DIR, 'images'), exist_ok=True)
        os.makedirs(os.path.join(MEDIA_DIR, 'badges'), exist_ok=True)
        os.makedirs(os.path.join(MEDIA_DIR, 'temp'), exist_ok=True)

        # Проверяем наличие необходимых библиотек
        try:
            import PIL
            import matplotlib
        except ImportError as e:
            logger.error(f"Missing required library: {e}")
            logger.error("Please install Pillow and matplotlib: pip install Pillow matplotlib")

        # Создаем плейсхолдер, если его нет
        placeholder_path = os.path.join(MEDIA_DIR, 'placeholder.png')
        if not os.path.exists(placeholder_path):
            buffer = create_placeholder_image()
            with open(placeholder_path, 'wb') as f:
                f.write(buffer.getvalue())
    except Exception as e:
        logger.error(f"Error ensuring media directories: {e}")
        logger.error(traceback.format_exc())

# В функцию get_image_path добавим создание заглушки
def get_image_path(file_name: str) -> str:
    # Удаляем начальный слэш, если есть
    if file_name.startswith('/') or file_name.startswith('\\'):
        file_name = file_name[1:]

    # Используем os.path.join для корректных путей независимо от платформы
    if os.path.dirname(file_name):
        full_path = os.path.join(MEDIA_DIR, file_name)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
    else:
        # Если указано только имя файла, ищем в директории images
        full_path = os.path.join(MEDIA_DIR, 'images', file_name)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Проверяем существование файла
    if not os.path.exists(full_path):
        logger.warning(f"Image file not found: {full_path}")
        # Возвращаем путь к заглушке
        placeholder_path = os.path.join(MEDIA_DIR, 'placeholder.png')
        if not os.path.exists(placeholder_path):
            ensure_media_directories()  # Создаем директории и заглушку
        return placeholder_path

    return full_path

def resize_image(image_path: str, max_width: int = 800, max_height: int = 600) -> BytesIO:
    """
    Изменение размера изображения с сохранением пропорций

    Args:
        image_path: Путь к изображению
        max_width: Максимальная ширина
        max_height: Максимальная высота

    Returns:
        BytesIO: Буфер с измененным изображением
    """
    try:
        img = Image.open(image_path)

        # Получаем оригинальные размеры
        width, height = img.size

        # Вычисляем новые размеры с сохранением пропорций
        if width > max_width or height > max_height:
            ratio = min(max_width / width, max_height / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
            img = img.resize((new_width, new_height), Image.LANCZOS)

        # Сохраняем в буфер
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return buffer

    except Exception as e:
        logger.error(f"Error resizing image {image_path}: {e}")
        # Возвращаем пустой буфер в случае ошибки
        return BytesIO()


def create_placeholder_image(width: int = 400, height: int = 300, text: str = "Изображение недоступно") -> BytesIO:
    """
    Создание изображения-заглушки с текстом

    Args:
        width: Ширина изображения
        height: Высота изображения
        text: Текст для отображения

    Returns:
        BytesIO: Буфер с созданным изображением
    """
    try:
        # Создаем новое изображение
        img = Image.new('RGB', (width, height), color=(240, 240, 240))
        draw = ImageDraw.Draw(img)

        # Подбираем размер шрифта
        font_size = int(min(width, height) / 15)
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            # Если шрифт не найден, используем стандартный
            font = ImageFont.load_default()

        # Вычисляем положение текста
        text_width, text_height = get_text_dimensions(draw, text, font)
        position = ((width - text_width) // 2, (height - text_height) // 2)

        # Рисуем текст
        draw.text(position, text, fill=(100, 100, 100), font=font)

        # Рисуем рамку
        draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(200, 200, 200))

        # Сохраняем в буфер
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return buffer

    except Exception as e:
        logger.error(f"Error creating placeholder image: {e}")
        # Возвращаем пустой буфер в случае ошибки
        return BytesIO()


def create_achievement_badge(text: str, level: int = 1, size: Tuple[int, int] = (200, 200)) -> BytesIO:
    """
    Создание изображения значка достижения

    Args:
        text: Текст достижения
        level: Уровень достижения (1-3)
        size: Размер изображения (ширина, высота)

    Returns:
        BytesIO: Буфер с созданным изображением
    """
    try:
        width, height = size

        # Определяем цвет в зависимости от уровня
        if level == 1:
            color = (192, 192, 192)  # серебро
        elif level == 2:
            color = (212, 175, 55)  # золото
        elif level == 3:
            color = (150, 200, 255)  # синий (платина)
        else:
            color = (192, 192, 192)  # серебро по умолчанию

        # Создаем новое изображение с прозрачным фоном
        img = Image.new('RGBA', (width, height), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Рисуем круг
        circle_margin = int(width * 0.1)
        circle_pos = [(circle_margin, circle_margin), (width - circle_margin, height - circle_margin)]
        draw.ellipse(circle_pos, fill=color + (200,))  # добавляем альфа-канал

        # Рисуем звезду в центре
        center_x, center_y = width // 2, height // 2
        star_size = int(width * 0.3)
        star_points = []

        for i in range(5):
            # Внешние точки звезды
            angle = i * 2 * 3.14159 / 5 - 3.14159 / 2
            star_points.append((
                center_x + int(star_size * 1.0 * pow(0.97, i) * _cos(angle)),
                center_y + int(star_size * 1.0 * pow(0.97, i) * _sin(angle))
            ))

            # Внутренние точки звезды
            angle += 3.14159 / 5
            star_points.append((
                center_x + int(star_size * 0.4 * _cos(angle)),
                center_y + int(star_size * 0.4 * _sin(angle))
            ))

        draw.polygon(star_points, fill=(255, 255, 255, 220))

        # Добавляем текст
        font_size = int(width / (len(text) * 0.6) if len(text) > 0 else width / 10)
        font_size = min(font_size, int(height / 4))  # Ограничиваем размер шрифта

        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except OSError:
            font = ImageFont.load_default()

        text_width, text_height = get_text_dimensions(draw, text, font)
        text_position = ((width - text_width) // 2, height - text_height - int(height * 0.15))

        # Добавляем тень для текста
        draw.text((text_position[0] + 2, text_position[1] + 2), text, fill=(0, 0, 0, 128), font=font)
        draw.text(text_position, text, fill=(255, 255, 255, 255), font=font)

        # Сохраняем в буфер
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return buffer

    except Exception as e:
        logger.error(f"Error creating achievement badge: {e}")
        # Возвращаем пустой буфер в случае ошибки
        return BytesIO()


def create_chart_image(width: int = 800, height: int = 600, data: dict = None) -> BytesIO:
    """
    Создание простого графика на основе данных

    Args:
        width: Ширина изображения
        height: Высота изображения
        data: Словарь с данными для графика {метка: значение}

    Returns:
        BytesIO: Буфер с созданным изображением
    """
    try:
        # Проверяем данные
        if not data or not isinstance(data, dict) or not data:
            return create_placeholder_image(width, height, "Нет данных для графика")

        # Создаем новое изображение
        img = Image.new('RGB', (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Рисуем рамку и сетку
        margin = 50
        chart_width = width - 2 * margin
        chart_height = height - 2 * margin

        # Рамка
        draw.rectangle([(margin, margin), (width - margin, height - margin)], outline=(200, 200, 200))

        # Горизонтальные линии сетки
        grid_steps = 5
        for i in range(grid_steps + 1):
            y = margin + i * chart_height // grid_steps
            draw.line([(margin, y), (width - margin, y)], fill=(230, 230, 230), width=1)

        # Находим максимальное значение для масштабирования
        max_value = max(data.values())

        # Рисуем столбцы
        bar_count = len(data)
        bar_width = chart_width // (bar_count * 2)

        for i, (label, value) in enumerate(data.items()):
            # Вычисляем координаты столбца
            bar_height = int(chart_height * value / max_value) if max_value > 0 else 0
            bar_left = margin + i * (chart_width // bar_count) + bar_width // 2
            bar_top = height - margin - bar_height
            bar_right = bar_left + bar_width
            bar_bottom = height - margin

            # Рисуем столбец
            draw.rectangle([(bar_left, bar_top), (bar_right, bar_bottom)], fill=(100, 149, 237))

            # Добавляем метку
            try:
                font = ImageFont.truetype("arial.ttf", 12)
            except OSError:
                font = ImageFont.load_default()

            # Подписываем значение над столбцом
            value_text = str(value)
            text_width, text_height = get_text_dimensions(draw, value_text, font)
            draw.text(
                (bar_left + (bar_width - text_width) // 2, bar_top - text_height - 5),
                value_text,
                fill=(0, 0, 0),
                font=font
            )

            # Подписываем метку под столбцом
            label_text = str(label)
            if len(label_text) > 10:
                label_text = label_text[:10] + "..."

            text_width, text_height = get_text_dimensions(draw, value_text, font)
            draw.text(
                (bar_left + (bar_width - text_width) // 2, bar_bottom + 5),
                label_text,
                fill=(0, 0, 0),
                font=font
            )

        # Сохраняем в буфер
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        return buffer

    except Exception as e:
        logger.error(f"Error creating chart image: {e}")
        # Возвращаем пустой буфер в случае ошибки
        return BytesIO()


def _sin(angle: float) -> float:
    """Простая реализация синуса для создания звезды"""
    import math
    return math.sin(angle)


def _cos(angle: float) -> float:
    """Простая реализация косинуса для создания звезды"""
    import math
    return math.cos(angle)


def ensure_media_directories() -> None:
    """Создание необходимых директорий для медиа-файлов"""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, 'images'), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, 'badges'), exist_ok=True)
    os.makedirs(os.path.join(MEDIA_DIR, 'temp'), exist_ok=True)

    # Создаем плейсхолдер, если его нет
    placeholder_path = os.path.join(MEDIA_DIR, 'placeholder.png')
    if not os.path.exists(placeholder_path):
        buffer = create_placeholder_image()
        with open(placeholder_path, 'wb') as f:
            f.write(buffer.getvalue())