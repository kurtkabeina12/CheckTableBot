"""Telegram-бот: открывает WebApp расписания."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import db


load_dotenv(
    Path(__file__).resolve().parent / ".env"
)


logging.basicConfig(
    format=(
        "%(asctime)s - "
        "%(name)s - "
        "%(levelname)s - "
        "%(message)s"
    ),
    level=logging.INFO,
)


WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "http://localhost:8080",
).rstrip("/")


TOKEN = os.getenv(
    "BOT_TOKEN",
    "",
).strip()


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    text = (
        "🗓 *Планировщик смен*\n\n"
        f"Ссылка: {WEBAPP_URL}"
    )

    # Telegram WebApp требует HTTPS.
    #
    # Если WEBAPP_URL — HTTPS,
    # открываем именно как WebApp.
    #
    # Если локальный HTTP,
    # даём обычную ссылку для браузера.

    if WEBAPP_URL.startswith("https://"):
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📅 Открыть расписание",
                        web_app=WebAppInfo(
                            url=WEBAPP_URL
                        ),
                    )
                ]
            ]
        )
    else:
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📅 Открыть в браузере",
                        url=WEBAPP_URL,
                    )
                ]
            ]
        )

    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode="Markdown",
    )


async def help_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.message.reply_text(
        "1) Добавьте сотрудников "
        "и тип графика\n"
        "2) Для 2/2 и 3/3 укажите "
        "дату начала цикла\n"
        "3) Для «по дням» отметьте "
        "пн/ср и т.д.\n"
        "4) Внесите отпуска\n"
        "5) Нажмите «След. месяц» — "
        "график соберётся автоматически"
    )


def main() -> None:
    db.init_db()

    if not TOKEN:
        raise SystemExit(
            "Укажите BOT_TOKEN в файле .env"
        )

    if not WEBAPP_URL:
        raise SystemExit(
            "Укажите WEBAPP_URL в файле .env"
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_cmd,
        )
    )

    print(
        f"Бот запущен. WebApp: {WEBAPP_URL}"
    )

    app.run_polling()


if __name__ == "__main__":
    main()