"""FastAPI: API + раздача Telegram WebApp."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import time
import urllib.parse
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import schedule_engine


STATIC_DIR = (
    Path(__file__).resolve().parent / "webapp"
)

BOT_TOKEN = os.getenv(
    "BOT_TOKEN",
    ""
).strip()


app = FastAPI(
    title="Schedule WebApp"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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

    Возвращает разобранные данные при успешной проверке.
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

    # --------------------------------------------------------
    # Проверяем возраст auth_date.
    # Не принимаем бесконечно старый initData.
    # --------------------------------------------------------

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
    Получает и проверяет пользователя Telegram
    из заголовка X-Telegram-Init-Data.
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
            detail=(
                "Telegram user id отсутствует"
            ),
        )

    return user


# ============================================================
# TELEGRAM AUTH MIDDLEWARE
# ============================================================

@app.middleware("http")
async def telegram_auth_middleware(
    request: Request,
    call_next,
):
    # ========================================================
    # Не API → пропускаем
    # ========================================================

    if not request.url.path.startswith("/api/"):
        return await call_next(request)

    # ========================================================
    # Health → доступен без авторизации
    # ========================================================

    if request.url.path == "/api/health":
        return await call_next(request)

    # ========================================================
    # Telegram authentication
    # ========================================================

    try:
        user = get_telegram_user(request)

        tg_id = int(
            user["id"]
        )

        # ====================================================
        # Ищем пользователя в существующей accounts
        # ====================================================

        account = db.get_account_by_tg_id(
            tg_id
        )

        if not account:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Ваш Telegram аккаунт "
                        "не зарегистрирован в системе"
                    )
                },
            )

        # ====================================================
        # Сохраняем пользователя и account
        # для endpoint'ов
        # ====================================================

        request.state.telegram_user = user
        request.state.account = account

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
    Возвращает текущего Telegram-пользователя
    и его существующий account.
    """

    user = request.state.telegram_user
    account = request.state.account

    tg_id = int(
        user["id"]
    )

    return {
        "authenticated": True,

        "telegram": {
            "id": tg_id,
            "username": user.get(
                "username"
            ),
            "first_name": user.get(
                "first_name"
            ),
            "last_name": user.get(
                "last_name"
            ),
        },

        "account": account,
    }
# ============================================================
# ACCOUNTS
# ============================================================

@app.get("/api/accounts")
def api_list_accounts():

    """
    Список всех существующих аккаунтов.

    WebApp использует его для выбора сотрудника.
    """

    return db.list_accounts()


# ============================================================
# EMPLOYEES / SCHEDULE CONFIG
# ============================================================

@app.get("/api/employees")
def api_list_employees(
    all: bool = False,
):

    """
    all=true:
        все accounts, включая ещё не настроенных.

    all=false:
        только сотрудники с настроенным графиком.
    """

    if all:
        return db.list_accounts()

    return db.list_employees(
        active_only=True
    )


@app.post("/api/employees")
def api_add_employee(
    body: EmployeeIn,
):

    schedule_type = (
        body.schedule_type
        .strip()
        .lower()
    )

    if schedule_type in (
        "2/2",
        "3/3",
    ) and not body.cycle_start:

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
):

    # Нельзя через этот endpoint
    # поменять account.
    #
    # emp_id — ID существующего account.

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

    if schedule_type in (
        "2/2",
        "3/3",
    ) and not body.cycle_start:

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
):

    """
    ВАЖНО:

    account не удаляется.

    Удаляется только настройка
    его графика.
    """

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
    emp_id: int | None = None,
):

    return db.list_vacations(
        emp_id
    )


@app.post("/api/vacations")
def api_add_vacation(
    body: VacationIn,
):

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
):

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
):

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
):

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
):

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