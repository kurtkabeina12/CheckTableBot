"""Движок расписания: 2/2, 3/3, 5/2, фиксированные дни + отпуска."""

from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Any

import db


WEEKDAY_NAMES_RU = [
    "пн",
    "вт",
    "ср",
    "чт",
    "пт",
    "сб",
    "вс",
]

STATUS_WORK = "work"
STATUS_OFF = "off"
STATUS_VACATION = "vacation"


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value

    return date.fromisoformat(value)


def is_on_vacation(
    day: date,
    vacations: list[dict[str, Any]],
) -> bool:

    for vac in vacations:

        start = _parse_date(vac["start_date"])
        end = _parse_date(vac["end_date"])

        if start <= day <= end:
            return True

    return False


def is_work_day_by_pattern(
    emp: dict[str, Any],
    day: date,
) -> bool:

    stype = (
        emp.get("schedule_type")
        or ""
    ).strip().lower()

    # 2/2, 3/3
    if stype in ("2/2", "3/3"):

        work_n, rest_n = map(
            int,
            stype.split("/"),
        )

        cycle = work_n + rest_n

        cycle_start = emp.get("cycle_start")

        if not cycle_start:
            return False

        start = _parse_date(cycle_start)

        offset = (
            day - start
        ).days

        if offset < 0:
            return False

        position = offset % cycle

        return position < work_n

    # 5/2
    if stype == "5/2":
        return day.weekday() < 5

    # Дни недели
    if stype in (
        "weekdays",
        "fixed",
        "дни",
        "по дням",
    ):

        slots = emp.get("day_slots") or []

        if slots:

            return any(
                int(slot.get("weekday", -1))
                == day.weekday()
                for slot in slots
            )

        weekdays = emp.get("weekdays") or []

        return day.weekday() in set(
            int(x) for x in weekdays
        )

    return False


def format_time_range(
    time_start: str = "",
    time_end: str = "",
) -> str:

    start = (
        time_start or ""
    ).strip()

    end = (
        time_end or ""
    ).strip()

    if start and end:
        return f"{start}–{end}"

    if start:
        return start

    if end:
        return f"до {end}"

    return ""


def time_label(
    emp: dict[str, Any],
    day: date | None = None,
) -> str:

    stype = (
        emp.get("schedule_type")
        or ""
    ).strip().lower()

    if (
        day is not None
        and stype in (
            "weekdays",
            "fixed",
            "дни",
            "по дням",
        )
    ):

        slots = emp.get("day_slots") or []

        day_slots = [
            slot
            for slot in slots
            if int(
                slot.get("weekday", -1)
            ) == day.weekday()
        ]

        if day_slots:

            labels = [
                format_time_range(
                    slot.get("time_start", ""),
                    slot.get("time_end", ""),
                )
                for slot in day_slots
            ]

            return ", ".join(
                label
                for label in labels
                if label
            )

    return format_time_range(
        emp.get("time_start") or "",
        emp.get("time_end") or "",
    )


def slots_summary(
    emp: dict[str, Any],
) -> str:

    slots = emp.get("day_slots") or []

    if not slots:
        return _weekdays_label(
            emp.get("weekdays") or []
        )

    parts = []

    for slot in slots:

        weekday = int(
            slot["weekday"]
        )

        label = format_time_range(
            slot.get("time_start", ""),
            slot.get("time_end", ""),
        )

        name = (
            WEEKDAY_NAMES_RU[weekday]
            if 0 <= weekday <= 6
            else str(weekday)
        )

        parts.append(
            f"{name} {label}".strip()
        )

    return ", ".join(parts)


def month_days(
    year: int,
    month: int,
) -> list[date]:

    last = calendar.monthrange(
        year,
        month,
    )[1]

    return [
        date(year, month, day)
        for day in range(1, last + 1)
    ]


def next_month(
    from_day: date | None = None,
) -> tuple[int, int]:

    today = from_day or date.today()

    if today.month == 12:
        return today.year + 1, 1

    return today.year, today.month + 1


def generate_month(
    year: int,
    month: int,
) -> dict[str, Any]:

    """
    Генерирует график только на основании:

    accounts
    employee_schedules
    vacations
    """

    employees = db.list_employees(
        active_only=True
    )

    vacations = db.list_vacations()

    vacations_by_employee: dict[
        int,
        list[dict[str, Any]]
    ] = {}

    for vacation in vacations:

        vacations_by_employee.setdefault(
            vacation["emp_id"],
            [],
        ).append(vacation)

    days = month_days(
        year,
        month,
    )

    # --------------------------------------------------------
    # Колонки дней
    # --------------------------------------------------------

    day_columns = []

    for day in days:

        day_columns.append(
            {
                "date": day.isoformat(),
                "day": day.day,
                "weekday": day.weekday(),
                "weekday_name": (
                    WEEKDAY_NAMES_RU[
                        day.weekday()
                    ]
                ),
            }
        )

    # --------------------------------------------------------
    # Люди
    # --------------------------------------------------------

    people = []

    for emp in employees:

        emp_vacations = (
            vacations_by_employee.get(
                emp["id"],
                [],
            )
        )

        cells = []

        work_count = 0
        vacation_count = 0
        off_count = 0

        for day in days:

            if is_on_vacation(
                day,
                emp_vacations,
            ):

                status = STATUS_VACATION
                cell_time = ""

                vacation_count += 1

            elif is_work_day_by_pattern(
                emp,
                day,
            ):

                status = STATUS_WORK

                cell_time = time_label(
                    emp,
                    day,
                )

                work_count += 1

            else:

                status = STATUS_OFF
                cell_time = ""

                off_count += 1

            cells.append(
                {
                    "date": day.isoformat(),
                    "status": status,
                    "time": cell_time,
                }
            )

        people.append(
            {
                "id": emp["id"],
                "account_id": emp["account_id"],
                "name": emp["name"],
                "username": emp.get("username"),
                "tg_id": emp.get("tg_id"),

                "schedule_type": (
                    emp["schedule_type"]
                ),

                "cycle_start": (
                    emp.get("cycle_start")
                ),

                "weekdays": (
                    emp.get("weekdays") or []
                ),

                "weekdays_label": (
                    _weekdays_label(
                        emp.get("weekdays") or []
                    )
                ),

                "day_slots": (
                    emp.get("day_slots") or []
                ),

                "slots_label": slots_summary(
                    emp
                ),

                "time_start": (
                    emp.get("time_start") or ""
                ),

                "time_end": (
                    emp.get("time_end") or ""
                ),

                "time_label": time_label(
                    emp
                ),

                "cells": cells,

                "stats": {
                    "work": work_count,
                    "off": off_count,
                    "vacation": vacation_count,
                },
            }
        )

    # --------------------------------------------------------
    # Сводка по дням
    # --------------------------------------------------------

    by_day = []

    for index, column in enumerate(
        day_columns
    ):

        working_people = [
            person
            for person in people
            if person["cells"][index][
                "status"
            ] == STATUS_WORK
        ]

        working = [
            person["name"]
            for person in working_people
        ]

        working_with_time = []

        for person in working_people:

            cell_time = (
                person["cells"][index]
                .get("time")
                or ""
            )

            working_with_time.append(
                {
                    "name": person["name"],
                    "time": cell_time,
                    "label": (
                        f"{person['name']} "
                        f"({cell_time})"
                        if cell_time
                        else person["name"]
                    ),
                }
            )

        on_vacation = [
            person["name"]
            for person in people
            if person["cells"][index][
                "status"
            ] == STATUS_VACATION
        ]

        by_day.append(
            {
                **column,
                "working": working,
                "working_with_time": (
                    working_with_time
                ),
                "on_vacation": on_vacation,
                "working_count": len(
                    working
                ),
            }
        )

    # --------------------------------------------------------
    # Итог
    # --------------------------------------------------------

    total_work = sum(
        person["stats"]["work"]
        for person in people
    )

    payload = {
        "year": year,
        "month": month,

        "month_label": (
            f"{month:02d}.{year}"
        ),

        "generated_at": (
            datetime.now().isoformat(
                timespec="seconds"
            )
        ),

        "days": day_columns,

        "people": people,

        "by_day": by_day,

        "summary": {
            "employee_count": len(
                people
            ),
            "total_work_slots": total_work,
        },
    }

    db.save_schedule(
        year,
        month,
        payload,
        payload["generated_at"],
    )

    return payload


def generate_next_month() -> dict[str, Any]:

    year, month = next_month()

    return generate_month(
        year,
        month,
    )


def export_rows(
    payload: dict[str, Any],
) -> list[dict[str, str]]:

    days = payload["days"]
    people = payload["people"]

    status_ru = {
        STATUS_WORK: "Работа",
        STATUS_OFF: "Выходной",
        STATUS_VACATION: "Отпуск",
    }

    rows = []

    for index, day in enumerate(days):

        row = {
            "Дата": _parse_date(
                day["date"]
            ).strftime("%d.%m.%Y"),

            "День": day[
                "weekday_name"
            ],
        }

        for person in people:

            cell = person["cells"][
                index
            ]

            label = status_ru[
                cell["status"]
            ]

            if (
                cell["status"]
                == STATUS_WORK
                and cell.get("time")
            ):
                label = (
                    f"{label} "
                    f"{cell['time']}"
                )

            row[
                person["name"]
            ] = label

        rows.append(row)

    return rows


def _weekdays_label(
    weekdays: list[int],
) -> str:

    if not weekdays:
        return ""

    return ", ".join(
        WEEKDAY_NAMES_RU[day]
        for day in sorted(
            int(x)
            for x in weekdays
        )
        if 0 <= day <= 6
    )


def describe_pattern(
    emp: dict[str, Any],
) -> str:

    schedule_type = (
        emp.get("schedule_type")
        or ""
    )

    if schedule_type in (
        "2/2",
        "3/3",
    ):

        start = (
            emp.get("cycle_start")
            or "?"
        )

        time = format_time_range(
            emp.get("time_start")
            or "",
            emp.get("time_end")
            or "",
        )

        return (
            f"{schedule_type} с {start}"
            + (
                f" · {time}"
                if time
                else ""
            )
        )

    if schedule_type in (
        "weekdays",
        "fixed",
        "дни",
        "по дням",
    ):

        return (
            "дни: "
            + slots_summary(emp)
        )

    if schedule_type == "5/2":

        time = format_time_range(
            emp.get("time_start")
            or "",
            emp.get("time_end")
            or "",
        )

        return (
            "5/2 (пн–пт)"
            + (
                f" · {time}"
                if time
                else ""
            )
        )

    return schedule_type