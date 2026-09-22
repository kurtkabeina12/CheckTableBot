"""PostgreSQL слой для планировщика смен."""

from __future__ import annotations

import json
import os

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row


load_dotenv(
    Path(__file__).resolve().parent / ".env"
)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
).strip()


# ============================================================
# CONNECTION
# ============================================================

def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "Не задана переменная DATABASE_URL"
        )

    return psycopg.connect(
        DATABASE_URL,
        row_factory=dict_row,
    )


@contextmanager
def db() -> Iterator[Any]:
    conn = get_connection()

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# INIT DB
# ============================================================

def init_db() -> None:
    """Создаёт только таблицы приложения."""

    with db() as conn:

        # ----------------------------------------------------
        # Графики сотрудников
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_schedules (
                id SERIAL PRIMARY KEY,

                account_id INTEGER NOT NULL
                    REFERENCES accounts(id)
                    ON DELETE CASCADE,

                schedule_type TEXT NOT NULL,

                cycle_start DATE,

                weekdays JSONB,

                day_slots JSONB,

                time_start TEXT DEFAULT '',

                time_end TEXT DEFAULT '',

                active BOOLEAN NOT NULL DEFAULT TRUE,

                note TEXT DEFAULT '',

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                UNIQUE(account_id)
            )
            """
        )

        # ----------------------------------------------------
        # Отпуска
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vacations (
                id SERIAL PRIMARY KEY,

                account_id INTEGER NOT NULL
                    REFERENCES accounts(id)
                    ON DELETE CASCADE,

                start_date DATE NOT NULL,

                end_date DATE NOT NULL,

                comment TEXT DEFAULT '',

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                CONSTRAINT vacations_dates_check
                    CHECK (end_date >= start_date)
            )
            """
        )

        # ----------------------------------------------------
        # Сохранённые расписания
        # ----------------------------------------------------

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id SERIAL PRIMARY KEY,

                year INTEGER NOT NULL,

                month INTEGER NOT NULL,

                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                payload JSONB NOT NULL,

                UNIQUE(year, month)
            )
            """
        )


# ============================================================
# HELPERS
# ============================================================

def _normalize_day_slots(
    day_slots: list[Any] | None,
) -> list[dict[str, Any]]:

    result: list[dict[str, Any]] = []

    if not day_slots:
        return result

    for item in day_slots:

        if not isinstance(item, dict):
            continue

        try:
            weekday = int(
                item.get("weekday")
            )
        except (TypeError, ValueError):
            continue

        if weekday < 0 or weekday > 6:
            continue

        result.append(
            {
                "weekday": weekday,
                "time_start": str(
                    item.get("time_start") or ""
                ).strip(),
                "time_end": str(
                    item.get("time_end") or ""
                ).strip(),
            }
        )

    result.sort(
        key=lambda x: (
            x["weekday"],
            x["time_start"],
            x["time_end"],
        )
    )

    return result


def _weekdays_from_slots(
    day_slots: list[dict[str, Any]],
) -> list[int]:

    return sorted(
        {
            int(slot["weekday"])
            for slot in day_slots
        }
    )


def _prepare_employee(
    row: dict[str, Any],
) -> dict[str, Any]:

    data = dict(row)

    # Для schedule_engine и frontend
    data["id"] = data["account_id"]

    data["name"] = (
        data.get("username")
        or f"Сотрудник #{data['account_id']}"
    )

    weekdays = data.get("weekdays")

    if isinstance(weekdays, str):
        try:
            weekdays = json.loads(weekdays)
        except json.JSONDecodeError:
            weekdays = []

    data["weekdays"] = weekdays or []

    day_slots = data.get("day_slots")

    if isinstance(day_slots, str):
        try:
            day_slots = json.loads(day_slots)
        except json.JSONDecodeError:
            day_slots = []

    day_slots = _normalize_day_slots(
        day_slots
    )

    if not day_slots and data["weekdays"]:
        day_slots = [
            {
                "weekday": int(day),
                "time_start": (
                    data.get("time_start") or ""
                ),
                "time_end": (
                    data.get("time_end") or ""
                ),
            }
            for day in data["weekdays"]
        ]

    data["day_slots"] = day_slots

    if day_slots and not data["weekdays"]:
        data["weekdays"] = _weekdays_from_slots(
            day_slots
        )

    data["time_start"] = (
        data.get("time_start") or ""
    )

    data["time_end"] = (
        data.get("time_end") or ""
    )

    data["active"] = bool(
        data.get("active", False)
    )

    return data


# ============================================================
# ACCOUNTS / AUTH
# ============================================================

def get_account_by_id(
    account_id: int,
    include_password: bool = False,
) -> dict[str, Any] | None:
    """
    Получает account по внутреннему id.

    include_password=True нужен только для внутренних
    операций, если когда-нибудь потребуется password_hash.

    По умолчанию password_hash вообще не выбирается.
    """

    password_field = (
        ", a.password_hash"
        if include_password
        else ""
    )

    with db() as conn:

        row = conn.execute(
            f"""
            SELECT
                a.id,
                a.user_id,
                a.username,
                a.allowed_slots,
                a.tg_id,
                a.role
                {password_field},

                CASE
                    WHEN es.id IS NOT NULL
                    THEN TRUE
                    ELSE FALSE
                END AS configured,

                es.schedule_type,
                es.cycle_start,
                es.weekdays,
                es.day_slots,
                es.time_start,
                es.time_end,
                es.active,
                es.note

            FROM accounts a

            LEFT JOIN employee_schedules es
                ON es.account_id = a.id

            WHERE a.id = %s

            LIMIT 1
            """,
            (account_id,),
        ).fetchone()

        if not row:
            return None

        data = dict(row)

        data["name"] = (
            data.get("username")
            or f"Сотрудник #{data['id']}"
        )

        data["configured"] = bool(
            data.get("configured")
        )

        weekdays = data.get("weekdays")

        if isinstance(weekdays, str):
            try:
                weekdays = json.loads(
                    weekdays
                )
            except json.JSONDecodeError:
                weekdays = []

        data["weekdays"] = weekdays or []

        slots = data.get("day_slots")

        if isinstance(slots, str):
            try:
                slots = json.loads(slots)
            except json.JSONDecodeError:
                slots = []

        data["day_slots"] = _normalize_day_slots(
            slots
        )

        data["time_start"] = (
            data.get("time_start") or ""
        )

        data["time_end"] = (
            data.get("time_end") or ""
        )

        return data


def get_account_by_username(
    username: str,
) -> dict[str, Any] | None:
    """
    Получает account по логину.

    Используется при обычной авторизации
    через username + password.
    """

    with db() as conn:

        row = conn.execute(
            """
            SELECT
                id,
                user_id,
                username,
                allowed_slots,
                tg_id,
                password_hash,
                role

            FROM accounts

            WHERE username = %s

            LIMIT 1
            """,
            (username,),
        ).fetchone()

        if not row:
            return None

        return dict(row)


# ============================================================
# ACCOUNTS / EMPLOYEES
# ============================================================

def list_accounts() -> list[dict[str, Any]]:
    """
    Все существующие accounts.

    Используется WebApp для выбора сотрудника.

    password_hash здесь НИКОГДА не возвращается.
    """

    with db() as conn:

        rows = conn.execute(
            """
            SELECT
                a.id,
                a.username,
                a.tg_id,
                a.role,

                CASE
                    WHEN es.id IS NOT NULL
                    THEN TRUE
                    ELSE FALSE
                END AS configured,

                es.schedule_type,
                es.cycle_start,
                es.weekdays,
                es.day_slots,
                es.time_start,
                es.time_end,
                es.active,
                es.note

            FROM accounts a

            LEFT JOIN employee_schedules es
                ON es.account_id = a.id

            ORDER BY a.username
            """
        ).fetchall()

        result = []

        for row in rows:

            data = dict(row)

            data["name"] = (
                data.get("username")
                or f"Сотрудник #{data['id']}"
            )

            data["configured"] = bool(
                data.get("configured")
            )

            weekdays = data.get("weekdays")

            if isinstance(weekdays, str):
                try:
                    weekdays = json.loads(
                        weekdays
                    )
                except json.JSONDecodeError:
                    weekdays = []

            data["weekdays"] = weekdays or []

            slots = data.get("day_slots")

            if isinstance(slots, str):
                try:
                    slots = json.loads(
                        slots
                    )
                except json.JSONDecodeError:
                    slots = []

            data["day_slots"] = _normalize_day_slots(
                slots
            )

            data["time_start"] = (
                data.get("time_start") or ""
            )

            data["time_end"] = (
                data.get("time_end") or ""
            )

            result.append(data)

        return result


def get_account_by_tg_id(
    tg_id: int,
) -> dict[str, Any] | None:
    """
    Находит существующий account по Telegram ID.

    Новые accounts здесь НЕ создаются.
    """

    with db() as conn:

        row = conn.execute(
            """
            SELECT
                a.id,
                a.user_id,
                a.username,
                a.allowed_slots,
                a.tg_id,
                a.role,

                CASE
                    WHEN es.id IS NOT NULL
                    THEN TRUE
                    ELSE FALSE
                END AS configured,

                es.schedule_type,
                es.cycle_start,
                es.weekdays,
                es.day_slots,
                es.time_start,
                es.time_end,
                es.active,
                es.note

            FROM accounts a

            LEFT JOIN employee_schedules es
                ON es.account_id = a.id

            WHERE a.tg_id = %s

            LIMIT 1
            """,
            (tg_id,),
        ).fetchone()

        if not row:
            return None

        data = dict(row)

        data["name"] = (
            data.get("username")
            or f"Сотрудник #{data['id']}"
        )

        data["configured"] = bool(
            data.get("configured")
        )

        weekdays = data.get("weekdays")

        if isinstance(weekdays, str):
            try:
                weekdays = json.loads(
                    weekdays
                )
            except json.JSONDecodeError:
                weekdays = []

        data["weekdays"] = weekdays or []

        slots = data.get("day_slots")

        if isinstance(slots, str):
            try:
                slots = json.loads(
                    slots
                )
            except json.JSONDecodeError:
                slots = []

        data["day_slots"] = _normalize_day_slots(
            slots
        )

        data["time_start"] = (
            data.get("time_start") or ""
        )

        data["time_end"] = (
            data.get("time_end") or ""
        )

        return data


def list_employees(
    active_only: bool = True,
) -> list[dict[str, Any]]:
    """
    Только сотрудники, которым уже настроен график.
    """

    with db() as conn:

        sql = """
            SELECT
                es.id,
                es.account_id,
                es.schedule_type,
                es.cycle_start,
                es.weekdays,
                es.day_slots,
                es.time_start,
                es.time_end,
                es.active,
                es.note,
                es.created_at,
                es.updated_at,

                a.username,
                a.tg_id,
                a.role

            FROM employee_schedules es

            JOIN accounts a
                ON a.id = es.account_id
        """

        if active_only:
            sql += """
                WHERE es.active = TRUE
            """

        sql += """
            ORDER BY a.username
        """

        rows = conn.execute(
            sql
        ).fetchall()

        return [
            _prepare_employee(
                dict(row)
            )
            for row in rows
        ]


def get_employee(
    emp_id: int,
) -> dict[str, Any] | None:

    with db() as conn:

        row = conn.execute(
            """
            SELECT
                es.id,
                es.account_id,
                es.schedule_type,
                es.cycle_start,
                es.weekdays,
                es.day_slots,
                es.time_start,
                es.time_end,
                es.active,
                es.note,
                es.created_at,
                es.updated_at,

                a.username,
                a.tg_id,
                a.role

            FROM employee_schedules es

            JOIN accounts a
                ON a.id = es.account_id

            WHERE es.account_id = %s
            """,
            (emp_id,),
        ).fetchone()

        if not row:
            return None

        return _prepare_employee(
            dict(row)
        )


# ============================================================
# EMPLOYEE SCHEDULE
# ============================================================

def save_employee_schedule(
    account_id: int,
    schedule_type: str,
    cycle_start: str | None = None,
    weekdays: list[int] | None = None,
    day_slots: list[dict[str, Any]] | None = None,
    time_start: str = "",
    time_end: str = "",
    note: str = "",
    active: bool = True,
) -> dict[str, Any]:

    slots = _normalize_day_slots(
        day_slots
    )

    if weekdays is None and slots:
        weekdays = _weekdays_from_slots(
            slots
        )

    with db() as conn:

        account = conn.execute(
            """
            SELECT id
            FROM accounts
            WHERE id = %s
            """,
            (account_id,),
        ).fetchone()

        if not account:
            raise ValueError(
                f"Аккаунт с id={account_id} не найден"
            )

        conn.execute(
            """
            INSERT INTO employee_schedules (
                account_id,
                schedule_type,
                cycle_start,
                weekdays,
                day_slots,
                time_start,
                time_end,
                active,
                note,
                updated_at
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW()
            )

            ON CONFLICT(account_id)

            DO UPDATE SET
                schedule_type =
                    EXCLUDED.schedule_type,

                cycle_start =
                    EXCLUDED.cycle_start,

                weekdays =
                    EXCLUDED.weekdays,

                day_slots =
                    EXCLUDED.day_slots,

                time_start =
                    EXCLUDED.time_start,

                time_end =
                    EXCLUDED.time_end,

                active =
                    EXCLUDED.active,

                note =
                    EXCLUDED.note,

                updated_at =
                    NOW()
            """,
            (
                account_id,
                schedule_type,
                cycle_start,
                json.dumps(
                    weekdays or []
                ),
                json.dumps(
                    slots,
                    ensure_ascii=False,
                ),
                time_start or "",
                time_end or "",
                bool(active),
                note or "",
            ),
        )

    employee = get_employee(
        account_id
    )

    if not employee:
        raise RuntimeError(
            "Не удалось получить "
            "сохранённый график сотрудника"
        )

    return employee


def update_employee(
    emp_id: int,
    **fields: Any,
) -> dict[str, Any] | None:

    allowed = {
        "schedule_type",
        "cycle_start",
        "weekdays",
        "day_slots",
        "time_start",
        "time_end",
        "active",
        "note",
    }

    updates = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not updates:
        return get_employee(
            emp_id
        )

    if "day_slots" in updates:

        slots = _normalize_day_slots(
            updates["day_slots"]
        )

        updates["day_slots"] = json.dumps(
            slots,
            ensure_ascii=False,
        )

        if "weekdays" not in updates:
            updates["weekdays"] = (
                _weekdays_from_slots(
                    slots
                )
            )

    if (
        "weekdays" in updates
        and updates["weekdays"] is not None
        and not isinstance(
            updates["weekdays"],
            str,
        )
    ):
        updates["weekdays"] = json.dumps(
            updates["weekdays"]
        )

    columns = ", ".join(
        f"{key} = %s"
        for key in updates
    )

    values = list(
        updates.values()
    )

    values.append(emp_id)

    with db() as conn:

        conn.execute(
            f"""
            UPDATE employee_schedules

            SET
                {columns},
                updated_at = NOW()

            WHERE account_id = %s
            """,
            values,
        )

    return get_employee(
        emp_id
    )


def delete_employee(
    emp_id: int,
) -> bool:
    """
    Удаляем только настройку графика.
    Сам account НЕ удаляется.
    """

    with db() as conn:

        cur = conn.execute(
            """
            DELETE FROM employee_schedules

            WHERE account_id = %s
            """,
            (emp_id,),
        )

        return cur.rowcount > 0


# ============================================================
# VACATIONS
# ============================================================

def list_vacations(
    emp_id: int | None = None,
) -> list[dict[str, Any]]:

    with db() as conn:

        sql = """
            SELECT
                v.id,
                v.account_id AS emp_id,
                v.start_date,
                v.end_date,
                v.comment,
                a.username AS emp_name

            FROM vacations v

            JOIN accounts a
                ON a.id = v.account_id
        """

        params: list[Any] = []

        if emp_id is not None:

            sql += """
                WHERE v.account_id = %s
            """

            params.append(
                emp_id
            )

        sql += """
            ORDER BY v.start_date DESC
        """

        rows = conn.execute(
            sql,
            params,
        ).fetchall()

        result = []

        for row in rows:

            data = dict(row)

            if data.get("start_date"):
                data["start_date"] = (
                    data["start_date"].isoformat()
                )

            if data.get("end_date"):
                data["end_date"] = (
                    data["end_date"].isoformat()
                )

            result.append(data)

        return result


def add_vacation(
    emp_id: int,
    start_date: str,
    end_date: str,
    comment: str = "",
) -> dict[str, Any]:

    with db() as conn:

        account = conn.execute(
            """
            SELECT id
            FROM accounts
            WHERE id = %s
            """,
            (emp_id,),
        ).fetchone()

        if not account:
            raise ValueError(
                "Сотрудник не найден"
            )

        cur = conn.execute(
            """
            INSERT INTO vacations (
                account_id,
                start_date,
                end_date,
                comment
            )

            VALUES (
                %s,
                %s,
                %s,
                %s
            )

            RETURNING id
            """,
            (
                emp_id,
                start_date,
                end_date,
                comment,
            ),
        )

        vacation_id = (
            cur.fetchone()["id"]
        )

        row = conn.execute(
            """
            SELECT
                v.id,
                v.account_id AS emp_id,
                v.start_date,
                v.end_date,
                v.comment,
                a.username AS emp_name

            FROM vacations v

            JOIN accounts a
                ON a.id = v.account_id

            WHERE v.id = %s
            """,
            (vacation_id,),
        ).fetchone()

        data = dict(row)

        data["start_date"] = (
            data["start_date"].isoformat()
        )

        data["end_date"] = (
            data["end_date"].isoformat()
        )

        return data


def delete_vacation(
    vac_id: int,
) -> bool:

    with db() as conn:

        cur = conn.execute(
            """
            DELETE FROM vacations

            WHERE id = %s
            """,
            (vac_id,),
        )

        return cur.rowcount > 0


# ============================================================
# SAVED SCHEDULES
# ============================================================

def save_schedule(
    year: int,
    month: int,
    payload: dict[str, Any],
    created_at: str,
) -> None:

    with db() as conn:

        conn.execute(
            """
            INSERT INTO schedules (
                year,
                month,
                created_at,
                payload
            )

            VALUES (
                %s,
                %s,
                %s,
                %s
            )

            ON CONFLICT(year, month)

            DO UPDATE SET
                created_at =
                    EXCLUDED.created_at,

                payload =
                    EXCLUDED.payload
            """,
            (
                year,
                month,
                created_at,
                json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
            ),
        )


def get_schedule(
    year: int,
    month: int,
) -> dict[str, Any] | None:

    with db() as conn:

        row = conn.execute(
            """
            SELECT
                id,
                year,
                month,
                created_at,
                payload

            FROM schedules

            WHERE year = %s
              AND month = %s
            """,
            (
                year,
                month,
            ),
        ).fetchone()

        if not row:
            return None

        payload = row["payload"]

        if isinstance(
            payload,
            str,
        ):
            payload = json.loads(
                payload
            )

        return {
            "id": row["id"],
            "year": row["year"],
            "month": row["month"],
            "created_at": (
                row["created_at"].isoformat()
                if hasattr(
                    row["created_at"],
                    "isoformat",
                )
                else row["created_at"]
            ),
            "payload": payload,
        }