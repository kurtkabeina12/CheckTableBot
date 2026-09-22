"""FastAPI: API + раздача Telegram WebApp."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import secrets
import time
import urllib.parse
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

import db
import schedule_engine


# ============================================================
# SETTINGS
# ============================================================

STATIC_DIR = (
    Path(__file__).resolve().parent / "webapp"
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    "",
).strip()

SESSION_SECRET = os.getenv(
    "SESSION_SECRET",
    "",
).strip()

if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)

WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "",
).strip()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Schedule WebApp"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# SESSION
# ============================================================

# На Railway сайт работает через HTTPS.
#
# При локальном запуске http://localhost
# cookie тоже должна работать, поэтому
# https_only зависит от WEBAPP_URL.

HTTPS_ONLY = WEBAPP_URL.startswith(
    "https://"
)

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    max_age=7 * 24 * 60 * 60,
    same_site="lax",
    https_only=HTTPS_ONLY,
)


# ============================================================
# PASSWORD
# ============================================================

def hash_password(
    password: str,
) -> str:
    """
    Создаёт парольный hash в формате:

    scrypt$<salt>$<hash>
    """

    salt = secrets.token_bytes(16)

    password_hash = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=64,
    )

    return (
        "scrypt$"
        + salt.hex()
        + "$"
        + password_hash.hex()
    )


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    """
    Проверяет пароль против scrypt hash.

    Формат:

    scrypt$<salt>$<hash>
    """

    if not password_hash:
        return False

    parts = password_hash.split("$")

    if len(parts) != 3:
        return False

    algorithm = parts[0]
    salt_hex = parts[1]
    stored_hash_hex = parts[2]

    if algorithm != "scrypt":
        return False

    try:
        salt = bytes.fromhex(
            salt_hex
        )

        stored_hash = bytes.fromhex(
            stored_hash_hex
        )
    except ValueError:
        return False

    try:
        calculated_hash = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=16384,
            r=8,
            p=1,
            dklen=len(stored_hash),
        )
    except Exception:
        return False

    return hmac.compare_digest(
        calculated_hash,
        stored_hash,
    )


# ============================================================
# TELEGRAM WEBAPP AUTH
# ============================================================

def validate_telegram_init_data(
    init_data: str,
) -> dict:
    """
    Проверяет подпись Telegram WebApp initData.

    Telegram формирует initData на клиенте.
    Backend проверяет подпись с помощью BOT_TOKEN.
    """

    if not BOT_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="BOT_TOKEN не настроен на сервере",
        )

    if not init_data:
        raise HTTPException(
            status_code=401,
            detail="Telegram initData отсутствует",
        )

    try:
        parsed = dict(
            urllib.parse.parse_qsl(
                init_data,
                keep_blank_values=True,
            )
        )
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="Некорректный Telegram initData",
        ) from exc

    received_hash = parsed.pop(
        "hash",
        None,
    )

    if not received_hash:
        raise HTTPException(
            status_code=401,
            detail="В initData отсутствует hash",
        )

    data_check_string = "\n".join(
        f"{key}={parsed[key]}"
        for key in sorted(parsed)
    )

    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode(),
        hashlib.sha256,
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Недействительная подпись Telegram",
        )

    # Проверяем возраст initData.
    auth_date_raw = parsed.get(
        "auth_date"
    )

    if auth_date_raw:
        try:
            auth_date = int(
                auth_date_raw
            )

            now = int(
                time.time()
            )

            max_age = 24 * 60 * 60

            if now - auth_date > max_age:
                raise HTTPException(
                    status_code=401,
                    detail="Telegram initData устарел",
                )

        except ValueError as exc:
            raise HTTPException(
                status_code=401,
                detail="Некорректный auth_date",
            ) from exc

    return parsed


def get_telegram_user(
    request: Request,
) -> dict:
    """
    Получает Telegram-пользователя
    из X-Telegram-Init-Data.
    """

    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        "",
    )

    data = validate_telegram_init_data(
        init_data
    )

    user_raw = data.get(
        "user"
    )

    if not user_raw:
        raise HTTPException(
            status_code=401,
            detail="Пользователь Telegram не найден",
        )

    try:
        user = json.loads(
            user_raw
        )
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail=(
                "Некорректные данные "
                "пользователя Telegram"
            ),
        ) from exc

    tg_id = user.get(
        "id"
    )

    if not tg_id:
        raise HTTPException(
            status_code=401,
            detail="Telegram user id отсутствует",
        )

    return user


# ============================================================
# ACCOUNT HELPERS
# ============================================================

def get_session_account(
    request: Request,
):
    """
    Получает account из обычной web-сессии.
    """

    account_id = request.session.get(
        "account_id"
    )

    if not account_id:
        return None

    try:
        account_id = int(
            account_id
        )
    except (
        TypeError,
        ValueError,
    ):
        request.session.clear()
        return None

    account = db.get_account_by_id(
        account_id
    )

    if not account:
        request.session.clear()
        return None

    return account


def get_request_account(
    request: Request,
):
    """
    Определяет текущего пользователя.

    Приоритет:

    1. Telegram initData
    2. обычная web-сессия
    """

    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        "",
    ).strip()

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    if init_data:
        user = get_telegram_user(
            request
        )

        tg_id = int(
            user["id"]
        )

        account = db.get_account_by_tg_id(
            tg_id
        )

        if not account:
            raise HTTPException(
                status_code=403,
                detail=(
                    "Ваш Telegram аккаунт "
                    "не зарегистрирован в системе"
                ),
            )

        request.state.telegram_user = user
        request.state.account = account
        request.state.auth_type = "telegram"

        return account

    # --------------------------------------------------------
    # обычный сайт
    # --------------------------------------------------------

    account = get_session_account(
        request
    )

    if not account:
        raise HTTPException(
            status_code=401,
            detail="Необходима авторизация",
        )

    request.state.account = account
    request.state.auth_type = "password"

    return account


def require_admin(
    request: Request,
):
    """
    Проверяет роль пользователя.

    Только role=admin.
    """

    account = getattr(
        request.state,
        "account",
        None,
    )

    if not account:
        raise HTTPException(
            status_code=401,
            detail="Необходима авторизация",
        )

    if account.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав",
        )

    return account


# ============================================================
# AUTH MIDDLEWARE
# ============================================================

@app.middleware("http")
async def auth_middleware(
    request: Request,
    call_next,
):
    """
    Авторизация API.

    Telegram:
        X-Telegram-Init-Data

    Обычный сайт:
        session cookie
    """

    path = request.url.path

    # --------------------------------------------------------
    # Не API
    # --------------------------------------------------------

    if not path.startswith("/api/"):
        return await call_next(request)

    # --------------------------------------------------------
    # Health
    # --------------------------------------------------------

    if path == "/api/health":
        return await call_next(request)

    # --------------------------------------------------------
    # Login / Register / Logout
    # --------------------------------------------------------

    if path in (
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",
    ):
        return await call_next(request)

    # --------------------------------------------------------
    # /api/auth/me
    #
    # Его тоже проверяем отдельно внутри endpoint,
    # потому что он должен вернуть 401,
    # если пользователь не авторизован.
    # --------------------------------------------------------

    if path == "/api/auth/me":
        return await call_next(request)

    # --------------------------------------------------------
    # Все остальные API
    # --------------------------------------------------------

    try:
        get_request_account(
            request
        )

    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": exc.detail
            },
        )

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "detail": str(exc)
            },
        )

    return await call_next(request)


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ============================================================
# MODELS
# ============================================================

class LoginIn(BaseModel):
    username: str
    password: str


class RegisterIn(BaseModel):
    username: str
    password: str


class EmployeeIn(BaseModel):
    account_id: int
    schedule_type: str
    cycle_start: str | None = None
    weekdays: list[int] = Field(
        default_factory=list
    )
    day_slots: list[dict] = Field(
        default_factory=list
    )
    time_start: str = ""
    time_end: str = ""
    note: str = ""
    active: bool = True


class VacationIn(BaseModel):
    emp_id: int
    start_date: str
    end_date: str
    comment: str = ""


class GenerateIn(BaseModel):
    year: int | None = None
    month: int | None = None
    next_month: bool = True


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():
    return {
        "ok": True
    }


# ============================================================
# AUTH
# ============================================================

@app.get("/api/auth/me")
def api_auth_me(
    request: Request,
):
    """
    Возвращает текущего пользователя.

    Может быть:

    Telegram:
        authenticated = true
        auth_type = telegram

    Обычный сайт:
        authenticated = true
        auth_type = password

    Неавторизованный:
        401
    """

    try:
        account = get_request_account(
            request
        )
    except HTTPException:
        raise

    result = {
        "authenticated": True,
        "auth_type": getattr(
            request.state,
            "auth_type",
            None,
        ),
        "account": account,
    }

    # Telegram данные добавляем только
    # если пользователь пришёл из Telegram.

    telegram_user = getattr(
        request.state,
        "telegram_user",
        None,
    )

    if telegram_user:
        result["telegram"] = {
            "id": int(
                telegram_user["id"]
            ),
            "username": telegram_user.get(
                "username"
            ),
            "first_name": telegram_user.get(
                "first_name"
            ),
            "last_name": telegram_user.get(
                "last_name"
            ),
        }

    return result


@app.post("/api/auth/login")
def api_auth_login(
    body: LoginIn,
    request: Request,
):
    """
    Обычный вход с сайта.

    Telegram для этого endpoint не требуется.
    """

    username = body.username.strip()

    password = body.password

    if not username:
        raise HTTPException(
            status_code=400,
            detail="Введите логин",
        )

    if not password:
        raise HTTPException(
            status_code=400,
            detail="Введите пароль",
        )

    account = db.get_account_by_username(
        username
    )

    if not account:
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль",
        )

    password_hash = account.get(
        "password_hash"
    )

    if not password_hash:
        raise HTTPException(
            status_code=401,
            detail=(
                "Для этого пользователя "
                "не установлен пароль"
            ),
        )

    if not verify_password(
        password,
        password_hash,
    ):
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль",
        )

    # Удаляем старую сессию.
    request.session.clear()

    # Запоминаем account.
    request.session["account_id"] = int(
        account["id"]
    )

    return {
        "authenticated": True,
        "auth_type": "password",
        "account": account,
    }


@app.post("/api/auth/register")
def api_auth_register(
    body: RegisterIn,
    request: Request,
):
    """
    Регистрация пользователя с обычного сайта.

    Telegram здесь не используется.

    Новый пользователь получает:
        role = user
        tg_id = NULL
    """

    username = body.username.strip()
    password = body.password

    if len(username) < 3:
        raise HTTPException(
            status_code=400,
            detail=(
                "Логин должен содержать "
                "минимум 3 символа"
            ),
        )

    if len(password) < 6:
        raise HTTPException(
            status_code=400,
            detail=(
                "Пароль должен содержать "
                "минимум 6 символов"
            ),
        )

    # Проверяем, что username свободен.

    existing = db.get_account_by_username(
        username
    )

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Такой пользователь уже зарегистрирован",
        )

    password_hash = hash_password(
        password
    )

    # В твоей таблице accounts сейчас есть
    # обязательные поля:
    #
    # user_id
    # username
    # allowed_slots
    #
    # Поэтому для обычного сайта:
    #
    # user_id = username
    # allowed_slots = ""
    # tg_id = NULL
    # role = user

    try:
        with db.db() as conn:
            row = conn.execute(
                """
                INSERT INTO accounts (
                    user_id,
                    username,
                    allowed_slots,
                    tg_id,
                    password_hash,
                    role
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    NULL,
                    %s,
                    'user'
                )
                RETURNING
                    id,
                    user_id,
                    username,
                    allowed_slots,
                    tg_id,
                    password_hash,
                    role
                """,
                (
                    username,
                    username,
                    "",
                    password_hash,
                ),
            ).fetchone()

    except Exception as exc:
        # На случай race condition,
        # когда два пользователя одновременно
        # регистрируют одинаковый username.

        error_text = str(exc).lower()

        if (
            "unique" in error_text
            or "duplicate" in error_text
        ):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Такой пользователь "
                    "уже зарегистрирован"
                ),
            ) from exc

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    account = dict(row)

    # Никогда не отдаём password_hash
    # на frontend.

    account.pop(
        "password_hash",
        None,
    )

    # Автоматически авторизуем пользователя
    # после регистрации.

    request.session.clear()

    request.session["account_id"] = int(
        account["id"]
    )

    return {
        "authenticated": True,
        "auth_type": "password",
        "account": account,
    }


@app.post("/api/auth/logout")
def api_auth_logout(
    request: Request,
):
    """
    Выход из обычной web-сессии.
    """

    request.session.clear()

    return {
        "authenticated": False
    }


# ============================================================
# ACCOUNTS
# ============================================================

@app.get("/api/accounts")
def api_list_accounts(
    request: Request,
):
    """
    Список всех accounts.

    Только admin.
    """

    require_admin(
        request
    )

    return db.list_accounts()


# ============================================================
# EMPLOYEES / SCHEDULE CONFIG
# ============================================================

@app.get("/api/employees")
def api_list_employees(
    request: Request,
    all: bool = False,
):
    """
    all=true:
        все accounts.

    all=false:
        только настроенные сотрудники.

    Только admin.
    """

    require_admin(
        request
    )

    if all:
        return db.list_accounts()

    return db.list_employees(
        active_only=True
    )


@app.post("/api/employees")
def api_add_employee(
    body: EmployeeIn,
    request: Request,
):
    """
    Настройка графика сотрудника.

    Только admin.
    """

    require_admin(
        request
    )

    schedule_type = (
        body.schedule_type
        .strip()
        .lower()
    )

    if (
        schedule_type in (
            "2/2",
            "3/3",
        )
        and not body.cycle_start
    ):
        raise HTTPException(
            400,
            (
                "Для 2/2 и 3/3 "
                "укажите дату начала цикла"
            ),
        )

    slots = body.day_slots or []

    weekdays = (
        body.weekdays
        or [
            int(slot["weekday"])
            for slot in slots
            if "weekday" in slot
        ]
    )

    if schedule_type in (
        "weekdays",
        "fixed",
        "дни",
        "по дням",
    ):
        if not slots and not weekdays:
            raise HTTPException(
                400,
                (
                    "Добавьте хотя бы "
                    "один рабочий день"
                ),
            )

        schedule_type = "weekdays"

    try:
        return db.save_employee_schedule(
            account_id=body.account_id,
            schedule_type=schedule_type,
            cycle_start=body.cycle_start,
            weekdays=(
                weekdays
                if schedule_type == "weekdays"
                else None
            ),
            day_slots=(
                slots
                if schedule_type == "weekdays"
                else []
            ),
            time_start=body.time_start,
            time_end=body.time_end,
            note=body.note,
            active=body.active,
        )

    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        ) from exc

    except Exception as exc:
        raise HTTPException(
            500,
            str(exc),
        ) from exc


@app.put("/api/employees/{emp_id}")
def api_update_employee(
    emp_id: int,
    body: EmployeeIn,
    request: Request,
):
    """
    Изменение графика.

    Только admin.
    """

    require_admin(
        request
    )

    if body.account_id != emp_id:
        raise HTTPException(
            400,
            "account_id не совпадает с emp_id",
        )

    schedule_type = (
        body.schedule_type
        .strip()
        .lower()
    )

    if (
        schedule_type in (
            "2/2",
            "3/3",
        )
        and not body.cycle_start
    ):
        raise HTTPException(
            400,
            (
                "Для 2/2 и 3/3 "
                "укажите дату начала цикла"
            ),
        )

    slots = body.day_slots or []

    weekdays = (
        body.weekdays
        or [
            int(slot["weekday"])
            for slot in slots
            if "weekday" in slot
        ]
    )

    if schedule_type in (
        "fixed",
        "дни",
        "по дням",
    ):
        schedule_type = "weekdays"

    if schedule_type == "weekdays":
        if not slots and not weekdays:
            raise HTTPException(
                400,
                (
                    "Добавьте хотя бы "
                    "один рабочий день"
                ),
            )

    employee = db.update_employee(
        emp_id,
        schedule_type=schedule_type,
        cycle_start=body.cycle_start,
        weekdays=(
            weekdays
            if schedule_type == "weekdays"
            else None
        ),
        day_slots=(
            slots
            if schedule_type == "weekdays"
            else []
        ),
        time_start=body.time_start,
        time_end=body.time_end,
        note=body.note,
        active=body.active,
    )

    if not employee:
        raise HTTPException(
            404,
            "Сотрудник не настроен",
        )

    return employee


@app.delete("/api/employees/{emp_id}")
def api_delete_employee(
    emp_id: int,
    request: Request,
):
    """
    Удаляет только настройку графика.

    Сам account НЕ удаляется.

    Только admin.
    """

    require_admin(
        request
    )

    if not db.delete_employee(
        emp_id
    ):
        raise HTTPException(
            404,
            "Настройка сотрудника не найдена",
        )

    return {
        "ok": True
    }


# ============================================================
# VACATIONS
# ============================================================

@app.get("/api/vacations")
def api_list_vacations(
    request: Request,
    emp_id: int | None = None,
):
    """
    Отпуска доступны авторизованным пользователям.
    """

    return db.list_vacations(
        emp_id
    )


@app.post("/api/vacations")
def api_add_vacation(
    body: VacationIn,
    request: Request,
):
    """
    Добавление отпуска.
    """

    if body.end_date < body.start_date:
        raise HTTPException(
            400,
            "Дата окончания раньше начала",
        )

    if not db.get_employee(
        body.emp_id
    ):
        raise HTTPException(
            404,
            "Сотрудник не настроен",
        )

    try:
        return db.add_vacation(
            body.emp_id,
            body.start_date,
            body.end_date,
            body.comment,
        )

    except Exception as exc:
        raise HTTPException(
            400,
            str(exc),
        ) from exc


@app.delete("/api/vacations/{vac_id}")
def api_delete_vacation(
    vac_id: int,
    request: Request,
):
    """
    Удаление отпуска.
    """

    if not db.delete_vacation(
        vac_id
    ):
        raise HTTPException(
            404,
            "Отпуск не найден",
        )

    return {
        "ok": True
    }


# ============================================================
# SCHEDULE
# ============================================================

@app.post("/api/schedule/generate")
def api_generate(
    body: GenerateIn,
    request: Request,
):
    """
    Генерация расписания.

    Только admin.
    """

    require_admin(
        request
    )

    if (
        body.next_month
        and body.year is None
    ):
        return (
            schedule_engine
            .generate_next_month()
        )

    if (
        body.year is None
        or body.month is None
    ):
        raise HTTPException(
            400,
            (
                "Укажите year и month "
                "или next_month=true"
            ),
        )

    if not (
        1 <= body.month <= 12
    ):
        raise HTTPException(
            400,
            "Месяц должен быть 1–12",
        )

    return schedule_engine.generate_month(
        body.year,
        body.month,
    )


@app.get(
    "/api/schedule/{year}/{month}"
)
def api_get_schedule(
    year: int,
    month: int,
    request: Request,
):
    """
    Просмотр расписания.

    Доступно всем авторизованным пользователям.
    """

    if not (
        1 <= month <= 12
    ):
        raise HTTPException(
            400,
            "Месяц должен быть 1–12",
        )

    saved = db.get_schedule(
        year,
        month,
    )

    if saved:
        return saved["payload"]

    return schedule_engine.generate_month(
        year,
        month,
    )


@app.get(
    "/api/schedule/{year}/{month}/xlsx"
)
def api_export_xlsx(
    year: int,
    month: int,
    request: Request,
):
    """
    Экспорт расписания.

    Доступен всем авторизованным пользователям.
    """

    if not (
        1 <= month <= 12
    ):
        raise HTTPException(
            400,
            "Месяц должен быть 1–12",
        )

    payload = db.get_schedule(
        year,
        month,
    )

    if payload:
        data = payload["payload"]
    else:
        data = schedule_engine.generate_month(
            year,
            month,
        )

    rows = schedule_engine.export_rows(
        data
    )

    df = pd.DataFrame(
        rows
    )

    buf = io.BytesIO()

    df.to_excel(
        buf,
        index=False,
    )

    buf.seek(0)

    filename = (
        f"schedule_{year}_{month:02d}.xlsx"
    )

    return StreamingResponse(
        buf,
        media_type=(
            "application/"
            "vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition":
                (
                    f'attachment; '
                    f'filename="{filename}"'
                )
        },
    )


# ============================================================
# WEBAPP
# ============================================================

@app.get("/")
def index():
    return FileResponse(
        STATIC_DIR / "index.html"
    )


if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(
            directory=STATIC_DIR
        ),
        name="static",
    )


# ============================================================
# RUN
# ============================================================

def run() -> None:
    import uvicorn

    host = os.getenv(
        "WEBAPP_HOST",
        "0.0.0.0",
    )

    port = int(
        os.getenv(
            "WEBAPP_PORT",
            "8080",
        )
    )

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    run()