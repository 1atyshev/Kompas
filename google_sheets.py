from __future__ import annotations

import calendar
import json
import os
import re
import datetime as dt
import math
import random
from pathlib import Path
from typing import Iterable, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from db import db_session
from models import JournalEntry, JournalWeeklyReport, Tracker, TrackerGoal, TrackerLog, User


SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]
JOURNAL_SHEET_TITLE = "Дневник"
BASE_MONTH_START_ROW = 3
BASE_MONTH_STEP = 23
BASE_TRACKER_ROWS = 7
MONTH_NAME_COL = "I"
TOTAL_COL = "AO"
CURRENT_STREAK_COL = "AQ"
LONGEST_STREAK_COL = "AR"
GOAL_COL = "AS"
PROGRESS_COL = "AT"
MONTH_NAMES = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
}


def _tz_offset_minutes(tz: str) -> int:
    if not tz:
        return 0
    tz = tz.strip().upper()
    if tz in {"UTC", "GMT"}:
        return 0
    match = re.match(r"^(UTC|GMT)\s*([+-])\s*(\d{1,2})(?::(\d{2}))?$", tz)
    if not match:
        return 0
    sign = 1 if match.group(2) == "+" else -1
    hours = int(match.group(3))
    minutes = int(match.group(4) or 0)
    return sign * (hours * 60 + minutes)


def _google_tz_from_user(tz: str) -> str | None:
    offset = _tz_offset_minutes(tz)
    if offset == 0:
        return "UTC"
    if offset % 60 != 0:
        return None
    hours = offset // 60
    sign = "-" if hours > 0 else "+"
    return f"Etc/GMT{sign}{abs(hours)}"


def _get_user_tz(user_id: int) -> str:
    with db_session() as session:
        user = session.get(User, user_id)
        return user.tz if user and user.tz else "UTC"


def _set_spreadsheet_timezone(
    spreadsheet_id: str, user_id: int, creds: Credentials | None = None
) -> None:
    tz_value = _google_tz_from_user(_get_user_tz(user_id))
    if not tz_value:
        return
    sheets = _sheets_client_for_user(creds) if creds else _sheets_client()
    try:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSpreadsheetProperties": {
                            "properties": {"timeZone": tz_value},
                            "fields": "timeZone",
                        }
                    }
                ]
            },
        ).execute()
    except HttpError:
        return


def _get_credentials():
    key_path = os.getenv("GOOGLE_SA_JSON")
    if not key_path:
        raise RuntimeError("GOOGLE_SA_JSON is not set")
    return service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)


def _drive_parent_id() -> str | None:
    raw = os.getenv("GOOGLE_DRIVE_PARENT_ID", "").strip()
    if not raw:
        return None
    if "?" in raw:
        raw = raw.split("?", 1)[0]
    for pattern in (r"/folders/([a-zA-Z0-9-_]+)", r"[?&]id=([a-zA-Z0-9-_]+)"):
        match = re.search(pattern, raw)
        if match:
            return match.group(1)
    return raw


def get_service_account_email() -> str:
    key_path = os.getenv("GOOGLE_SA_JSON")
    if not key_path:
        return "service-account"
    try:
        data = json.loads(Path(key_path).read_text())
    except (OSError, json.JSONDecodeError):
        return "service-account"
    return data.get("client_email") or "service-account"


def _drive_client():
    return build("drive", "v3", credentials=_get_credentials(), cache_discovery=False)


def _sheets_client():
    return build("sheets", "v4", credentials=_get_credentials(), cache_discovery=False)


def _drive_client_for_user(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _sheets_client_for_user(creds: Credentials):
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _template_path() -> Path:
    return Path(__file__).resolve().parent / "habitbot_template_EN.xlsx"


def _date_key(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Google Sheets serial date (days since 1899-12-30)
        seconds = (float(value) - 25569) * 86400
        if seconds < 0:
            return None
        d = dt.datetime.utcfromtimestamp(seconds).date()
        return d.strftime("%Y-%m-%d")
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value)
            return parsed.date().strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _get_trackers_for_user(user_id: int) -> list[tuple[int, str, str]]:
    with db_session() as session:
        trackers = (
            session.query(Tracker)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(Tracker.order_index, Tracker.id)
            .all()
        )
    return [(t.id, t.name, t.type) for t in trackers]


def _get_tracker_objects_for_user(user_id: int) -> list[Tracker]:
    with db_session() as session:
        return (
            session.query(Tracker)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(Tracker.order_index, Tracker.id)
            .all()
        )


def _get_logs_for_user(user_id: int) -> list[tuple[int, dt.date, float, bool]]:
    with db_session() as session:
        logs = (
            session.query(TrackerLog)
            .join(Tracker, TrackerLog.tracker_id == Tracker.id)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(TrackerLog.date, TrackerLog.tracker_id, TrackerLog.id)
            .all()
        )
    return [(l.tracker_id, l.date, float(l.value), bool(l.partial)) for l in logs]


def _month_start_rows(row_count: int, step: int = BASE_MONTH_STEP) -> list[int]:
    rows = []
    start = BASE_MONTH_START_ROW
    for i in range(12):
        row = start + step * i
        if row <= row_count:
            rows.append(row)
    return rows


def _detect_month_name_rows(sheets, spreadsheet_id: str, grid_title: str) -> list[int]:
    values = (
        sheets.spreadsheets()
        .values()
        .get(
            spreadsheetId=spreadsheet_id,
            range=f"{grid_title}!{MONTH_NAME_COL}1:{MONTH_NAME_COL}400",
        )
        .execute()
        .get("values", [])
    )
    rows: list[int] = []
    for idx, row in enumerate(values, start=1):
        value = row[0].strip().lower() if row else ""
        if value in MONTH_NAMES:
            rows.append(idx)
    return rows


def _month_starts_from_names(month_name_rows: list[int], row_count: int) -> list[int]:
    starts = [row + 2 for row in month_name_rows]
    if len(starts) == 12:
        return starts
    return _month_start_rows(row_count, BASE_MONTH_STEP)


def _month_blocks(
    month_name_rows: list[int],
    row_count: int,
    step: int,
) -> list[tuple[int, int]]:
    if len(month_name_rows) == 12:
        blocks: list[tuple[int, int]] = []
        for idx, name_row in enumerate(month_name_rows):
            start_row = name_row + 2
            end_row = (month_name_rows[idx + 1] - 1) if idx + 1 < 12 else row_count
            blocks.append((start_row, end_row))
        return blocks
    starts = _month_start_rows(row_count, step)
    blocks = []
    for idx, start_row in enumerate(starts):
        end_row = start_row + step - 1
        blocks.append((start_row, min(end_row, row_count)))
    return blocks


def _ensure_tracker_rows(
    sheets,
    spreadsheet_id: str,
    grid_id: int,
    row_count: int,
    tracker_count: int,
    month_name_rows: list[int],
) -> None:
    if len(month_name_rows) != 12:
        return
    month_starts = [row + 2 for row in month_name_rows]
    available_rows = []
    for idx, start_row in enumerate(month_starts):
        next_name = month_name_rows[idx + 1] if idx + 1 < len(month_name_rows) else None
        if next_name:
            available = max(0, next_name - start_row)
        else:
            available = max(0, row_count - start_row)
        available_rows.append(available)
    min_available = min(available_rows) if available_rows else BASE_TRACKER_ROWS
    if tracker_count <= min_available:
        return
    delta = tracker_count - min_available
    requests = []
    for idx in range(len(month_name_rows) - 1, -1, -1):
        insert_before = (
            month_name_rows[idx + 1] - 1 if idx + 1 < len(month_name_rows) else row_count
        )
        insert_index = insert_before
        requests.append(
            {
                "insertDimension": {
                    "range": {
                        "sheetId": grid_id,
                        "dimension": "ROWS",
                        "startIndex": insert_index,
                        "endIndex": insert_index + delta,
                    },
                    "inheritFromBefore": False,
                }
            }
        )
    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()


def _ensure_visible_rows(
    sheets,
    spreadsheet_id: str,
    grid_id: int,
    month_starts: list[int],
    tracker_count: int,
) -> None:
    if tracker_count <= 0:
        return
    requests = []
    for start_row in month_starts:
        start_index = start_row - 1
        end_index = start_index + tracker_count
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": grid_id,
                        "dimension": "ROWS",
                        "startIndex": start_index,
                        "endIndex": end_index,
                    },
                    "properties": {"hiddenByUser": False},
                    "fields": "hiddenByUser",
                }
            }
        )
    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()


def _col_to_a1(col: int) -> str:
    result = []
    while col > 0:
        col, rem = divmod(col - 1, 26)
        result.append(chr(ord("A") + rem))
    return "".join(reversed(result))


def _period_key(date: dt.date, period: str) -> dt.date:
    if period == "day":
        return date
    if period == "week":
        return date - dt.timedelta(days=date.weekday())
    if period == "month":
        return date.replace(day=1)
    if period == "year":
        return date.replace(month=1, day=1)
    return date


def _next_period_start(date: dt.date, period: str) -> dt.date:
    if period == "day":
        return date + dt.timedelta(days=1)
    if period == "week":
        return date + dt.timedelta(days=7)
    if period == "month":
        year = date.year + (date.month // 12)
        month = 1 if date.month == 12 else date.month + 1
        return dt.date(year, month, 1)
    if period == "year":
        return dt.date(date.year + 1, 1, 1)
    return date + dt.timedelta(days=1)


def _get_tracker_goals(tracker_id: int) -> dict[str, float]:
    with db_session() as session:
        rows = (
            session.query(TrackerGoal)
            .filter(TrackerGoal.tracker_id == tracker_id)
            .all()
        )
    return {r.period: float(r.target) for r in rows}


def _load_count_xp_map(tracker: Tracker) -> dict[int, int]:
    raw = tracker.xp_count_map
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    mapping: dict[int, int] = {}
    for key, value in data.items():
        try:
            mapping[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return mapping


def _tracker_xp_for_value(tracker: Tracker, value: float, partial: bool = False) -> int:
    if value <= 0:
        return 0
    if tracker.type == "binary":
        base = int(tracker.xp or 10)
        if partial:
            return max(1, base // 2)
        return max(1, base)
    if tracker.type == "time":
        earned = int(value * (tracker.xp or 0))
        return max(1, earned) if value > 0 else 0
    if tracker.type == "count":
        mapping = _load_count_xp_map(tracker)
        if mapping:
            if float(value).is_integer():
                return int(mapping.get(int(value), 0))
            return 0
        fallback = int(tracker.xp or 0)
        fallback = min(fallback, 10) if fallback else 0
        return max(1, fallback) if fallback else 0
    if tracker.type == "scale":
        if tracker.xp_scale_min is not None and tracker.xp_scale_max is not None:
            v = max(1.0, min(10.0, float(value)))
            earned = tracker.xp_scale_min + (v - 1) * (tracker.xp_scale_max - tracker.xp_scale_min) / 9
            return int(round(earned))
        fallback = int(tracker.xp or 0)
        fallback = min(fallback, 10) if fallback else 0
        return max(1, fallback) if fallback else 0
    fallback = int(tracker.xp or 0)
    return max(1, fallback) if fallback else 0


def _period_success(
    tracker: Tracker,
    stats: dict[dt.date, dict[str, float | bool]],
    period: str,
    goals: dict[str, float],
    key: dt.date,
) -> bool:
    entry = stats.get(key)
    if not entry:
        return False
    mode = tracker.streak_mode or "activity"
    if mode == "goal":
        target = goals.get(period, 0)
        if not target or target <= 0:
            return False
        total = float(entry["total"])
        return total >= target

    if tracker.type == "binary":
        if tracker.streak_partial_ok is False:
            return bool(entry.get("has_full"))
        return bool(entry.get("has_any"))

    threshold = float(tracker.streak_min_value or 0)
    total = float(entry["total"])
    if threshold <= 0:
        return total > 0
    return total >= threshold


def _build_period_stats(
    logs: list[tuple[dt.date, float, bool]],
    period: str,
) -> dict[dt.date, dict[str, float | bool]]:
    stats: dict[dt.date, dict[str, float | bool]] = {}
    for date, value, partial in logs:
        key = _period_key(date, period)
        entry = stats.setdefault(key, {"total": 0.0, "has_any": False, "has_full": False})
        entry["total"] = float(entry["total"]) + float(value)
        entry["has_any"] = True
        if not partial:
            entry["has_full"] = True
    return stats


def _current_streak(
    tracker: Tracker,
    stats: dict[dt.date, dict[str, float | bool]],
    goals: dict[str, float],
    today: dt.date,
) -> int:
    if tracker.streak_enabled is False:
        return 0
    mode = tracker.streak_mode or "activity"
    period = tracker.streak_period or "day"
    if mode == "goal" and period not in {"week", "month", "year"}:
        return 0
    if mode != "goal" and period not in {"day", "week", "month"}:
        period = "day"
    streak = 0
    current = today
    for _ in range(366):
        key = _period_key(current, period)
        if not _period_success(tracker, stats, period, goals, key):
            break
        streak += 1
        current = key - dt.timedelta(days=1)
    return streak


def _longest_streak(
    tracker: Tracker,
    stats: dict[dt.date, dict[str, float | bool]],
    goals: dict[str, float],
    today: dt.date,
    min_date: dt.date | None,
) -> int:
    if tracker.streak_enabled is False or min_date is None:
        return 0
    mode = tracker.streak_mode or "activity"
    period = tracker.streak_period or "day"
    if mode == "goal" and period not in {"week", "month", "year"}:
        return 0
    if mode != "goal" and period not in {"day", "week", "month"}:
        period = "day"
    current = _period_key(min_date, period)
    end = _period_key(today, period)
    best = 0
    streak = 0
    while current <= end:
        if _period_success(tracker, stats, period, goals, current):
            streak += 1
            if streak > best:
                best = streak
        else:
            streak = 0
        current = _next_period_start(current, period)
    return best


def sync_habits_grid_with_credentials(
    spreadsheet_id: str, user_id: int, creds: Credentials, delete_setup: bool = True
) -> None:
    sheets = _sheets_client_for_user(creds)
    _set_spreadsheet_timezone(spreadsheet_id, user_id, creds)
    meta = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    locale = (meta.get("properties", {}).get("locale") or "").lower()
    use_ru = locale.startswith("ru")
    sum_fn = "СУММ" if use_ru else "SUM"
    countif_fn = "СЧЁТЕСЛИ" if use_ru else "COUNTIF"
    count_fn = "СЧЁТ" if use_ru else "COUNT"
    avg_fn = "СРЗНАЧ" if use_ru else "AVERAGE"
    arg_sep = ";" if use_ru else ","
    sheet_map = {s["properties"]["title"]: s["properties"]["sheetId"] for s in meta.get("sheets", [])}

    grid_title = "Habits Tracker 2026"
    grid_id = sheet_map.get(grid_title)
    if grid_id is None:
        return

    requests = []
    if delete_setup:
        setup_id = sheet_map.get("Setup")
        if setup_id is not None:
            requests.append({"deleteSheet": {"sheetId": setup_id}})

    tracker_objs = _get_tracker_objects_for_user(user_id)
    trackers = [(t.id, t.name, t.type) for t in tracker_objs]
    if not trackers:
        if requests:
            sheets.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": requests}
            ).execute()
        _sync_monthly_sheet(
            sheets,
            spreadsheet_id,
            sheet_map,
            tracker_objs,
            {},
            dt.date.today(),
            count_fn,
            sum_fn,
            avg_fn,
            arg_sep,
        )
        return

    grid_props = next(
        (s["properties"] for s in meta.get("sheets", []) if s["properties"]["title"] == grid_title),
        {},
    )
    row_count = grid_props.get("gridProperties", {}).get("rowCount", 0) or 0
    month_name_rows = _detect_month_name_rows(sheets, spreadsheet_id, grid_title)
    _ensure_tracker_rows(
        sheets, spreadsheet_id, grid_id, row_count, len(trackers), month_name_rows
    )
    if month_name_rows:
        month_name_rows = _detect_month_name_rows(sheets, spreadsheet_id, grid_title)
    month_starts = _month_starts_from_names(month_name_rows, row_count)
    _ensure_visible_rows(sheets, spreadsheet_id, grid_id, month_starts, len(trackers))
    blocks = _month_blocks(
        month_name_rows,
        row_count,
        BASE_MONTH_STEP,
    )

    if trackers:
        clear_ranges = []
        for start_row, end_row in blocks:
            clear_start = start_row + len(trackers)
            if clear_start <= end_row:
                clear_ranges.append(f"{grid_title}!I{clear_start}:AT{end_row}")
        if clear_ranges:
            sheets.spreadsheets().values().batchClear(
                spreadsheetId=spreadsheet_id,
                body={"ranges": clear_ranges},
            ).execute()

    list_time_count = [0, 0.5, 1, 1.5, 2, 3, 4, 5, 6, 7, 8, 10, 12]
    list_scale = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    # Write tracker names and validations.
    value_updates = []
    for start_row in month_starts:
        for idx, (_, name, ttype) in enumerate(trackers):
            row = start_row + idx
            value_updates.append(
                {"range": f"{grid_title}!I{row}", "values": [[name]]}
            )
            if ttype == "binary":
                rule = {"condition": {"type": "BOOLEAN"}, "showCustomUi": True, "strict": False}
            elif ttype == "scale":
                rule = {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": str(v)} for v in list_scale],
                    },
                    "showCustomUi": False,
                    "strict": False,
                }
            else:
                rule = {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": str(v)} for v in list_time_count],
                    },
                    "showCustomUi": False,
                    "strict": False,
                }
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": grid_id,
                            "startRowIndex": row - 1,
                            "endRowIndex": row,
                            "startColumnIndex": 9,
                            "endColumnIndex": 40,
                        },
                        "rule": rule,
                    }
                }
            )

    if value_updates:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": value_updates},
        ).execute()

    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id, body={"requests": requests}
        ).execute()

    # Fill existing logs into grid.
    logs = _get_logs_for_user(user_id)

    tracker_by_id = {tid: (idx, ttype) for idx, (tid, _, ttype) in enumerate(trackers)}
    grid_updates = []
    month_key_by_start: dict[int, tuple[int, int]] = {}
    for start_row in month_starts:
        date_row = start_row - 2
        date_values = (
            sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=spreadsheet_id,
                range=f"{grid_title}!J{date_row}:AN{date_row}",
                valueRenderOption="UNFORMATTED_VALUE",
                dateTimeRenderOption="SERIAL_NUMBER",
            )
            .execute()
            .get("values", [[]])
        )
        if not date_values:
            continue
        col_by_date = {}
        month_key = None
        for idx, val in enumerate(date_values[0]):
            key = _date_key(val)
            if key:
                col_by_date[key] = 10 + idx  # J = 10
                if month_key is None:
                    try:
                        parsed = dt.datetime.fromisoformat(key).date()
                        month_key = (parsed.year, parsed.month)
                    except ValueError:
                        pass
        if month_key:
            month_key_by_start[start_row] = month_key

        for tracker_id, date, value, _partial in logs:
            meta = tracker_by_id.get(tracker_id)
            if not meta:
                continue
            idx, ttype = meta
            row = start_row + idx
            key = date.strftime("%Y-%m-%d")
            col = col_by_date.get(key)
            if not col:
                continue
            cell_value = value >= 1 if ttype == "binary" else value
            col_letter = _col_to_a1(col)
            grid_updates.append(
                {"range": f"{grid_title}!{col_letter}{row}", "values": [[cell_value]]}
            )

    if grid_updates:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": grid_updates},
        ).execute()

    if not tracker_objs:
        return

    today = dt.date.today()
    logs_by_tracker: dict[int, list[tuple[dt.date, float, bool]]] = {}
    for tracker_id, date, value, partial in logs:
        logs_by_tracker.setdefault(tracker_id, []).append((date, value, partial))

    summary_updates = []
    formula_updates = []
    week_start = today - dt.timedelta(days=today.weekday())
    week_end = week_start + dt.timedelta(days=6)

    for idx, tracker in enumerate(tracker_objs):
        tracker_logs = logs_by_tracker.get(tracker.id, [])
        goals = _get_tracker_goals(tracker.id)
        stats = _build_period_stats(tracker_logs, tracker.streak_period or "day")
        current = _current_streak(tracker, stats, goals, today)
        tracker_min_date = min((d for d, _v, _p in tracker_logs), default=None)
        longest = _longest_streak(tracker, stats, goals, today, tracker_min_date)
        week_goal = goals.get("week")
        month_goal = goals.get("month")
        year_goal = goals.get("year")
        day_goal = goals.get("day")
        week_values = [v for d, v, _p in tracker_logs if week_start <= d <= week_end]
        week_total = sum(week_values)
        week_avg = (week_total / len(week_values)) if week_values else 0.0
        if week_goal and month_goal:
            goal_display = f"Нед: {week_goal} / Мес: {month_goal}"
        elif week_goal:
            goal_display = f"Нед: {week_goal}"
        elif month_goal:
            goal_display = f"Мес: {month_goal}"
        elif year_goal:
            goal_display = f"Год: {year_goal}"
        elif day_goal:
            goal_display = f"День: {day_goal}"
        elif tracker.target:
            goal_display = f"{tracker.target}"
        else:
            goal_display = ""
        for start_row in month_starts:
            row = start_row + idx
            month_key = month_key_by_start.get(start_row)
            is_current_month = month_key == (today.year, today.month) if month_key else False
            if month_key:
                year, month = month_key
                month_values = [
                    v for d, v, _p in tracker_logs if d.year == year and d.month == month
                ]
                month_total = sum(month_values)
                month_avg = (month_total / len(month_values)) if month_values else 0.0
            else:
                month_values = [v for _d, v, _p in tracker_logs]
                month_total = sum(month_values)
                month_avg = (month_total / len(month_values)) if month_values else 0.0
            week_metric = week_avg if tracker.type == "scale" else week_total
            month_metric = month_avg if tracker.type == "scale" else month_total
            progress_value = ""
            if week_goal and month_goal:
                if is_current_month:
                    week_pct = (
                        f"{round((week_metric / week_goal) * 100)}%"
                        if week_goal > 0
                        else ""
                    )
                    month_pct = (
                        f"{round((month_metric / month_goal) * 100)}%"
                        if month_goal > 0
                        else ""
                    )
                    if week_pct and month_pct:
                        progress_value = f"{week_pct} / {month_pct}"
                    else:
                        progress_value = week_pct or month_pct
            elif month_goal:
                if is_current_month:
                    progress_value = (
                        f"{round((month_metric / month_goal) * 100)}%"
                        if month_goal > 0
                        else ""
                    )
            elif week_goal:
                if is_current_month:
                    progress_value = (
                        f"{round((week_metric / week_goal) * 100)}%"
                        if week_goal > 0
                        else ""
                    )
            elif year_goal and year_goal > 0:
                if is_current_month:
                    year_values = [
                        v for d, v, _p in tracker_logs if d.year == today.year
                    ]
                    year_total = sum(year_values)
                    year_metric = (
                        (year_total / len(year_values)) if year_values else 0.0
                    )
                    if tracker.type == "scale":
                        progress_value = f"{round((year_metric / year_goal) * 100)}%"
                    else:
                        progress_value = f"{round((year_total / year_goal) * 100)}%"
            elif day_goal and day_goal > 0:
                if is_current_month:
                    day_values = [v for d, v, _p in tracker_logs if d == today]
                    day_total = sum(day_values)
                    day_metric = (day_total / len(day_values)) if day_values else 0.0
                    if tracker.type == "scale":
                        progress_value = f"{round((day_metric / day_goal) * 100)}%"
                    else:
                        progress_value = f"{round((day_total / day_goal) * 100)}%"
            elif tracker.target:
                if is_current_month:
                    target_value = float(tracker.target or 0)
                    if target_value > 0:
                        progress_value = (
                            f"{round((month_metric / target_value) * 100)}%"
                        )
            summary_updates.append(
                {
                    "range": f"{grid_title}!{CURRENT_STREAK_COL}{row}:{PROGRESS_COL}{row}",
                    "values": [[
                        current if is_current_month else "",
                        longest if is_current_month else "",
                        goal_display if is_current_month else "",
                        progress_value,
                    ]],
                }
            )
            formula_updates.append(
                {
                    "range": f"{grid_title}!{TOTAL_COL}{row}",
                    "values": [[
                        f"={countif_fn}(J{row}:AN{row}{arg_sep} TRUE)"
                        if tracker.type == "binary"
                        else f"={sum_fn}(J{row}:AN{row})"
                    ]],
                }
            )

    if summary_updates:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "RAW", "data": summary_updates},
        ).execute()
    if formula_updates:
        sheets.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"valueInputOption": "USER_ENTERED", "data": formula_updates},
        ).execute()

    _sync_monthly_sheet(
        sheets,
        spreadsheet_id,
        sheet_map,
        tracker_objs,
        logs_by_tracker,
        today,
        count_fn,
        sum_fn,
        avg_fn,
        arg_sep,
    )
    _sync_monthly_demo(
        sheets,
        spreadsheet_id,
        sheet_map,
        today,
        count_fn,
        avg_fn,
        arg_sep,
        tracker_objs,
        logs_by_tracker,
    )


def sync_habits_grid(
    spreadsheet_id: str, user_id: int, delete_setup: bool = True
) -> None:
    creds = _get_credentials()
    sync_habits_grid_with_credentials(
        spreadsheet_id, user_id, creds, delete_setup=delete_setup
    )


def _sync_monthly_sheet(
    sheets,
    spreadsheet_id: str,
    sheet_map: dict,
    tracker_objs: list[Tracker],
    logs_by_tracker: dict[int, list[tuple[dt.date, float, bool]]],
    today: dt.date,
    count_fn: str,
    sum_fn: str,
    avg_fn: str,
    arg_sep: str,
) -> None:
    title = "Ежемесячник"
    sheet_id = sheet_map.get(title)
    if sheet_id is None:
        resp = sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

    month_label = [
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ][today.month - 1]
    month_title = f"{month_label.capitalize()} {today.year}"

    start_month = today.replace(day=1)
    if start_month.month == 12:
        end_month = start_month.replace(year=start_month.year + 1, month=1, day=1) - dt.timedelta(days=1)
    else:
        end_month = start_month.replace(month=start_month.month + 1, day=1) - dt.timedelta(days=1)
    days_in_month = end_month.day
    start_weekday = start_month.weekday()  # 0 = Monday
    week_count = (start_weekday + days_in_month + 6) // 7
    total_day_cols = week_count * 7

    name_col = 0
    day_start_col = 1
    day_col_px = 24
    analysis_start_col = day_start_col + total_day_cols
    analysis_cols = 2
    helper_start_col = analysis_start_col + analysis_cols + 1
    helper_cols = total_day_cols
    ncols = 1 + total_day_cols + analysis_cols + 1 + helper_cols
    chart_row_count = 11
    chart_row_height = 20

    day_slots: list[dt.date | None] = [None] * total_day_cols
    for day in range(1, days_in_month + 1):
        idx = start_weekday + (day - 1)
        if idx < total_day_cols:
            day_slots[idx] = dt.date(start_month.year, start_month.month, day)

    tracker_by_id = {tracker.id: tracker for tracker in tracker_objs}
    goals_by_tracker = {tracker.id: _get_tracker_goals(tracker.id) for tracker in tracker_objs}
    daily_logs_by_tracker: dict[int, dict[dt.date, list[tuple[float, bool]]]] = {}
    daily_xp_by_day: dict[dt.date, int] = {}
    for tracker_id, entries in logs_by_tracker.items():
        daily: dict[dt.date, list[tuple[float, bool]]] = {}
        tracker = tracker_by_id.get(tracker_id)
        for date, value, partial in entries:
            if date < start_month or date > end_month:
                continue
            daily.setdefault(date, []).append((float(value), bool(partial)))
            if tracker is not None:
                daily_xp_by_day[date] = daily_xp_by_day.get(date, 0) + _tracker_xp_for_value(
                    tracker, float(value), bool(partial)
                )
        daily_logs_by_tracker[tracker_id] = daily

    days_in_year = 366 if calendar.isleap(start_month.year) else 365

    def _daily_target(tracker: Tracker, goals: dict[str, float]) -> float:
        month_goal = goals.get("month") or 0
        week_goal = goals.get("week") or 0
        year_goal = goals.get("year") or 0
        day_goal = goals.get("day") or 0
        if month_goal > 0:
            return month_goal / days_in_month
        if week_goal > 0:
            return week_goal / 7
        if year_goal > 0:
            return year_goal / days_in_year
        if day_goal > 0:
            return day_goal
        if tracker.target:
            return float(tracker.target)
        if tracker.type == "binary":
            return 1.0
        return 0.0

    def _daily_actual(tracker: Tracker, entries: list[tuple[float, bool]]) -> float:
        if not entries:
            return 0.0
        if tracker.type == "binary":
            if any(not partial for _v, partial in entries):
                return 1.0
            return 0.5
        values = [v for v, _p in entries]
        if tracker.type == "scale":
            return sum(values) / len(values)
        return sum(values)

    def _format_number(value: float) -> str:
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        if not text:
            text = "0"
        return text.replace(".", ",") if arg_sep == ";" else text

    def _format_decimal(value: float) -> str:
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text.replace(".", ",") if arg_sep == ";" else text

    def _sparkline_bar(value_literal: str, max_literal: str) -> str:
        # In locales with ";" as arg separator, array columns use "\" instead of ",".
        col_sep = "\\" if arg_sep == ";" else ","
        row_sep = ";"
        options = (
            f'{{"charttype"{col_sep}"bar"{row_sep}"max"{col_sep}{max_literal}'
            f'{row_sep}"color1"{col_sep}"#cfe3c8"'
            f'{row_sep}"color2"{col_sep}"#efe6de"}}'
        )
        return f"=SPARKLINE({value_literal}{arg_sep}{options})"

    def _pick_xp_step(max_value: float) -> int:
        if max_value <= 10:
            return 2
        if max_value <= 25:
            return 5
        if max_value <= 60:
            return 10
        if max_value <= 120:
            return 20
        if max_value <= 300:
            return 50
        if max_value <= 600:
            return 100
        return 200

    daily_target_by_tracker = {
        tracker.id: _daily_target(tracker, goals_by_tracker.get(tracker.id, {}))
        for tracker in tracker_objs
    }

    progress_series: list[str | float] = []
    xp_series: list[str | int] = []
    activity_counts: list[str | int] = []
    missing_counts: list[str | int] = []
    total_expected = 0.0
    total_done = 0.0
    daily_activity_by_day: dict[int, int] = {}

    for slot_idx, date in enumerate(day_slots):
        if not date:
            progress_series.append("")
            activity_counts.append("")
            missing_counts.append("")
            xp_series.append("")
            continue
        expected = 0.0
        done = 0.0
        activity_count = 0
        for tracker in tracker_objs:
            entries = daily_logs_by_tracker.get(tracker.id, {}).get(date, [])
            actual = _daily_actual(tracker, entries)
            if actual > 0:
                activity_count += 1
            target = daily_target_by_tracker.get(tracker.id, 0.0)
            if target > 0:
                expected += target
                done += min(actual, target)
        if expected > 0:
            progress_value = done / expected
        else:
            progress_value = (activity_count / len(tracker_objs)) if tracker_objs else 0.0
        progress_series.append(progress_value)
        activity_counts.append(activity_count)
        missing_counts.append(max(len(tracker_objs) - activity_count, 0))
        total_expected += expected
        total_done += done
        daily_activity_by_day[date.day] = activity_count
        xp_series.append(daily_xp_by_day.get(date, 0))

    overall_progress = total_done / total_expected if total_expected > 0 else 0.0
    avg_progress = (
        sum(p for p in progress_series if isinstance(p, (int, float)))
        / max(len([p for p in progress_series if isinstance(p, (int, float))]), 1)
    )
    total_completions = sum(v for v in activity_counts if isinstance(v, int))
    xp_values = [v for v in xp_series if isinstance(v, (int, float))]
    xp_max_value = max(xp_values, default=0)
    xp_step = _pick_xp_step(float(xp_max_value))
    xp_axis_max = max(xp_step, int(math.ceil(float(xp_max_value) / xp_step) * xp_step))
    xp_series_smooth: list[str | float] = []
    smooth_window = 2
    for idx, value in enumerate(xp_series):
        if not isinstance(value, (int, float)):
            xp_series_smooth.append("")
            continue
        window_vals: list[float] = []
        for j in range(idx - smooth_window, idx + smooth_window + 1):
            if 0 <= j < len(xp_series):
                v = xp_series[j]
                if isinstance(v, (int, float)):
                    window_vals.append(float(v))
        if window_vals:
            smooth_value = sum(window_vals) / len(window_vals)
            xp_series_smooth.append(round(smooth_value, 2))
        else:
            xp_series_smooth.append(float(value))

    def _tint(color: dict[str, float], amount: float) -> dict[str, float]:
        return {
            "red": min(1.0, color["red"] + (1.0 - color["red"]) * amount),
            "green": min(1.0, color["green"] + (1.0 - color["green"]) * amount),
            "blue": min(1.0, color["blue"] + (1.0 - color["blue"]) * amount),
        }

    week_palette = [
        {"red": 0.953, "green": 0.863, "blue": 0.824},
        {"red": 0.929, "green": 0.882, "blue": 0.824},
        {"red": 0.902, "green": 0.871, "blue": 0.788},
        {"red": 0.867, "green": 0.902, "blue": 0.843},
        {"red": 0.843, "green": 0.890, "blue": 0.867},
        {"red": 0.886, "green": 0.906, "blue": 0.918},
    ]
    week_body_palette = [_tint(color, 0.35) for color in week_palette]

    def pad_row(values: list) -> list:
        return values + [""] * (ncols - len(values))

    # Header rows
    rows: list[list] = []
    header_row = [""] * ncols
    header_row[name_col] = month_label.capitalize()
    weekly_progress_value = _format_number(avg_progress)
    kpi_labels = [
        ("Кол-во привычек", len(tracker_objs)),
        ("Кол-во выполненных привычек", total_completions),
        ("Еженедельный прогресс", _sparkline_bar(weekly_progress_value, "1")),
        ("Прогресс %", f"{round(overall_progress * 100, 2)}%"),
    ]
    kpi_span = 6
    kpi_gap = 2
    kpi_starts = [3 + i * (kpi_span + kpi_gap) for i in range(len(kpi_labels))]
    kpi_end_col = min(ncols, kpi_starts[-1] + kpi_span) if kpi_starts else ncols
    for (label, _value), col in zip(kpi_labels, kpi_starts):
        if col < ncols:
            header_row[col] = label
    rows.append(pad_row(header_row))

    value_row = [""] * ncols
    for (_label, value), col in zip(kpi_labels, kpi_starts):
        if col < ncols:
            value_row[col] = value
    rows.append(pad_row(value_row))
    rows.append(pad_row([]))

    week_header = ["Посаженные привычки"]
    for week in range(week_count):
        week_header.append(f"Неделя {week + 1}")
        week_header.extend([""] * 6)
    week_header.extend(["Анализ", "Прогресс"])
    rows.append(pad_row(week_header))

    dow_labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    dow_row = [""]
    for idx in range(total_day_cols):
        dow_row.append(dow_labels[idx % 7])
    dow_row.extend(["День", "Итого"])
    rows.append(pad_row(dow_row))

    # Habit rows (pad with empty rows to keep a stable grid height)
    min_grid_rows = max(len(tracker_objs), 10)
    for tracker in tracker_objs:
        row = [tracker.name]
        target = daily_target_by_tracker.get(tracker.id, 0.0)
        daily_map = daily_logs_by_tracker.get(tracker.id, {})
        visible_values: list = []
        ratio_values: list = []
        for date in day_slots:
            if not date:
                visible_values.append("")
                ratio_values.append("")
                continue
            entries = daily_map.get(date, [])
            actual = _daily_actual(tracker, entries)
            if target > 0:
                ratio = min(actual / target, 1.0)
            else:
                ratio = 1.0 if actual > 0 else 0.0
            if tracker.type == "binary":
                has_full = any(not partial for _v, partial in entries)
                visible_values.append(True if has_full else False)
            else:
                visible_values.append(round(actual, 2) if actual > 0 else "")
            ratio_values.append(round(ratio, 3) if ratio > 0 else 0)
        row.extend(visible_values)
        row.extend(["", ""])
        row.append("")
        row.extend(ratio_values)
        rows.append(pad_row(row))

    for _ in range(max(min_grid_rows - len(tracker_objs), 0)):
        filler = [""]
        filler.extend([""] * total_day_cols)
        filler.extend(["", ""])
        filler.append("")
        filler.extend([""] * helper_cols)
        rows.append(pad_row(filler))

    data_start_row = 6
    data_rows = min_grid_rows if tracker_objs else 0
    data_end_row = data_start_row + data_rows - 1 if data_rows else data_start_row - 1

    # Progress rows
    progress_row = ["Прогресс"]
    for val in progress_series:
        progress_row.append(val)
    progress_row.extend(["", ""])
    progress_row.append("")
    progress_row.extend([""] * helper_cols)
    rows.append(pad_row(progress_row))

    filled_row = ["Заполнено"]
    for val in activity_counts:
        filled_row.append(val)
    filled_row.extend(["", ""])
    filled_row.append("")
    filled_row.extend([""] * helper_cols)
    rows.append(pad_row(filled_row))

    missing_row = ["Незаполнено"]
    for val in missing_counts:
        missing_row.append(val)
    missing_row.extend(["", ""])
    missing_row.append("")
    missing_row.extend([""] * helper_cols)
    rows.append(pad_row(missing_row))

    xp_scale_rows = [""] * chart_row_count
    steps = max(int(xp_axis_max / xp_step), 1)
    tick_count = min(5, steps + 1)
    if tick_count < 2:
        tick_count = 2
    row_positions = [
        round(i * (chart_row_count - 1) / (tick_count - 1)) for i in range(tick_count)
    ]
    tick_values = []
    for i in range(tick_count):
        step_idx = round(i * steps / (tick_count - 1))
        tick_values.append(int(step_idx * xp_step))
    tick_values = list(reversed(tick_values))
    for row_idx, value in zip(row_positions, tick_values):
        if 0 <= row_idx < chart_row_count:
            xp_scale_rows[row_idx] = str(value)

    for idx in range(chart_row_count):
        row = [""] * ncols
        row[name_col] = xp_scale_rows[idx]
        rows.append(row)

    progress_row_index = data_start_row + data_rows
    filled_row_index = progress_row_index + 1
    missing_row_index = progress_row_index + 2
    chart_start_row_index = missing_row_index + 1
    chart_end_row_index = chart_start_row_index + chart_row_count - 1
    xp_row_index = chart_end_row_index + 1
    xp_smooth_row_index = xp_row_index + 1
    days_row_index = xp_smooth_row_index + 1

    xp_row = ["XP"]
    for val in xp_series:
        xp_row.append(val)
    xp_row.extend(["", ""])
    xp_row.append("")
    xp_row.extend([""] * helper_cols)
    rows.append(pad_row(xp_row))

    xp_smooth_row = ["XP (smooth)"]
    for val in xp_series_smooth:
        xp_smooth_row.append(val)
    xp_smooth_row.extend(["", ""])
    xp_smooth_row.append("")
    xp_smooth_row.extend([""] * helper_cols)
    rows.append(pad_row(xp_smooth_row))

    days_row = ["Дни"]
    for date in day_slots:
        days_row.append(date.day if date else "")
    days_row.extend(["", ""])
    days_row.append("")
    days_row.extend([""] * helper_cols)
    rows.append(pad_row(days_row))

    # Analysis block: last 10 days
    analysis_days = list(range(days_in_month, max(days_in_month - 9, 0), -1))
    analysis_rows = min(len(analysis_days), data_rows)
    for i in range(analysis_rows):
        day_num = analysis_days[i]
        count = daily_activity_by_day.get(day_num, 0)
        row_idx = data_start_row + i - 1
        if 0 <= row_idx < len(rows):
            rows[row_idx][analysis_start_col] = day_num
            rows[row_idx][analysis_start_col + 1] = _sparkline_bar(
                str(count), str(max(len(tracker_objs), 1))
            )

    last_row = len(rows)
    last_col = _col_to_a1(ncols)

    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A:{last_col}",
    ).execute()

    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A1:{last_col}{last_row}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    # Collect existing charts + conditional formats for cleanup
    sheet_info = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties,charts,conditionalFormats)",
    ).execute()
    chart_delete_requests = []
    cf_delete_requests = []
    for sheet in sheet_info.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") != sheet_id:
            continue
        for chart in sheet.get("charts", []):
            chart_id = chart.get("chartId")
            if chart_id is not None:
                chart_delete_requests.append({"deleteEmbeddedObject": {"objectId": chart_id}})
        cond_rules = sheet.get("conditionalFormats", []) or []
        for idx in range(len(cond_rules) - 1, -1, -1):
            cf_delete_requests.append(
                {
                    "deleteConditionalFormatRule": {
                        "sheetId": sheet_id,
                        "index": idx,
                    }
                }
            )

    base_bg = {"red": 1.0, "green": 1.0, "blue": 1.0}
    card_bg = {"red": 0.976, "green": 0.965, "blue": 0.953}
    header_bg = {"red": 0.973, "green": 0.955, "blue": 0.941}
    kpi_bg = header_bg
    kpi_bar_bg = {"red": 0.947, "green": 0.921, "blue": 0.894}
    panel_bg = {"red": 0.969, "green": 0.945, "blue": 0.925}
    name_bg = {"red": 0.969, "green": 0.941, "blue": 0.918}
    analysis_bg = {"red": 0.949, "green": 0.918, "blue": 0.894}
    border_color = {"red": 0.90, "green": 0.88, "blue": 0.85}
    card_border_color = {"red": 0.82, "green": 0.78, "blue": 0.74}

    merge_requests = [
        {
            "mergeCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3,
                },
                "mergeType": "MERGE_ALL",
            }
        }
    ]
    for col in kpi_starts:
        if col + kpi_span <= ncols:
            merge_requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": col,
                            "endColumnIndex": col + kpi_span,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )
            merge_requests.append(
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": col,
                            "endColumnIndex": col + kpi_span,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                }
            )

    # Merge week headers
    for week in range(week_count):
        start_col = day_start_col + week * 7
        merge_requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 3,
                        "endRowIndex": 4,
                        "startColumnIndex": start_col,
                        "endColumnIndex": start_col + 7,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )

    data_block_end = (data_end_row + 1) if data_end_row >= data_start_row else data_start_row
    day_end_col = day_start_col + total_day_cols
    topbar_end_col = analysis_start_col + analysis_cols

    format_requests = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"hideGridlines": True}},
                "fields": "gridProperties.hideGridlines",
            }
        },
        {
            "unmergeCells": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": max(last_row + 15, 40),
                    "startColumnIndex": 0,
                    "endColumnIndex": ncols,
                }
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": max(last_row + 15, 40),
                    "startColumnIndex": 0,
                    "endColumnIndex": ncols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": base_bg
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": days_row_index,
                    "startColumnIndex": 0,
                    "endColumnIndex": topbar_end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": card_bg
                    }
                },
                "fields": "userEnteredFormat.backgroundColor",
            }
        },
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row - 1,
                    "endRowIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "rule": None,
            }
        },
        *merge_requests,
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": topbar_end_col,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": header_bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 0,
                    "endIndex": 1,
                },
                "properties": {"pixelSize": 40},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": 2,
                },
                "properties": {"pixelSize": 28},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 3,
                    "endIndex": 4,
                },
                "properties": {"pixelSize": 22},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": 4,
                    "endIndex": 5,
                },
                "properties": {"pixelSize": 20},
                "fields": "pixelSize",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 3,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": False,
                            "fontSize": 26,
                            "fontFamily": "Georgia",
                            "foregroundColor": {"red": 0.74, "green": 0.56, "blue": 0.56},
                        },
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 3,
                    "endColumnIndex": kpi_end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": False,
                            "fontSize": 8,
                            "foregroundColor": {"red": 0.42, "green": 0.42, "blue": 0.42},
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "wrapStrategy": "WRAP",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment,wrapStrategy)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": 2,
                    "startColumnIndex": 3,
                    "endColumnIndex": kpi_end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "bold": True,
                            "fontSize": 12,
                            "foregroundColor": {"red": 0.25, "green": 0.22, "blue": 0.21},
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 3,
                    "endRowIndex": 5,
                    "startColumnIndex": analysis_start_col,
                    "endColumnIndex": analysis_start_col + analysis_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": analysis_bg,
                        "textFormat": {"bold": True, "fontSize": 9},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 3,
                    "endRowIndex": 4,
                    "startColumnIndex": 0,
                    "endColumnIndex": ncols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 8},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 4,
                    "endRowIndex": 5,
                    "startColumnIndex": 0,
                    "endColumnIndex": ncols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": False, "fontSize": 8},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row - 1,
                    "endRowIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
                    "startColumnIndex": name_col,
                    "endColumnIndex": name_col + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 10},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row - 1,
                    "endRowIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                        "numberFormat": {"type": "NUMBER", "pattern": "0.##"},
                    }
                },
                "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment,numberFormat)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": progress_row_index - 1,
                    "endRowIndex": progress_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "PERCENT", "pattern": "0%"},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": filled_row_index - 1,
                    "endRowIndex": missing_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "0"},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": xp_row_index - 1,
                    "endRowIndex": xp_smooth_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": "0"},
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(numberFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": data_start_row - 1,
                    "endRowIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "top": {"style": "SOLID", "width": 1, "color": border_color},
                "bottom": {"style": "SOLID", "width": 1, "color": border_color},
                "left": {"style": "SOLID", "width": 1, "color": border_color},
                "right": {"style": "SOLID", "width": 1, "color": border_color},
                "innerHorizontal": {"style": "SOLID", "width": 1, "color": border_color},
                "innerVertical": {"style": "SOLID", "width": 1, "color": border_color},
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": name_col,
                    "endIndex": name_col + 1,
                },
                "properties": {"pixelSize": 180},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": day_start_col,
                    "endIndex": day_start_col + total_day_cols,
                },
                "properties": {"pixelSize": day_col_px},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": analysis_start_col,
                    "endIndex": analysis_start_col + analysis_cols,
                },
                "properties": {"pixelSize": 70},
                "fields": "pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": helper_start_col,
                    "endIndex": helper_start_col + helper_cols,
                },
                "properties": {"hiddenByUser": True, "pixelSize": 1},
                "fields": "hiddenByUser,pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": data_start_row - 1,
                    "endIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
                },
                "properties": {"pixelSize": 20, "hiddenByUser": False},
                "fields": "pixelSize,hiddenByUser",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": progress_row_index - 1,
                    "endIndex": missing_row_index,
                },
                "properties": {"pixelSize": 18, "hiddenByUser": False},
                "fields": "pixelSize,hiddenByUser",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": progress_row_index - 1,
                    "endIndex": progress_row_index,
                },
                "properties": {"pixelSize": 24, "hiddenByUser": False},
                "fields": "pixelSize,hiddenByUser",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": chart_start_row_index - 1,
                    "endIndex": chart_end_row_index,
                },
                "properties": {"pixelSize": chart_row_height, "hiddenByUser": False},
                "fields": "pixelSize,hiddenByUser",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": xp_row_index - 1,
                    "endIndex": xp_row_index,
                },
                "properties": {"hiddenByUser": False, "pixelSize": 2},
                "fields": "hiddenByUser,pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": xp_smooth_row_index - 1,
                    "endIndex": xp_smooth_row_index,
                },
                "properties": {"hiddenByUser": False, "pixelSize": 2},
                "fields": "hiddenByUser,pixelSize",
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "ROWS",
                    "startIndex": days_row_index - 1,
                    "endIndex": days_row_index,
                },
                "properties": {"hiddenByUser": False, "pixelSize": 16},
                "fields": "hiddenByUser,pixelSize",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": days_row_index - 1,
                    "endRowIndex": days_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 8,
                            "foregroundColor": {"red": 0.55, "green": 0.55, "blue": 0.55},
                        },
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                        "padding": {"left": 3},
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment,padding)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": chart_start_row_index - 1,
                    "endRowIndex": chart_end_row_index,
                    "startColumnIndex": name_col,
                    "endColumnIndex": name_col + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 8,
                            "foregroundColor": {"red": 0.45, "green": 0.45, "blue": 0.45},
                        },
                        "horizontalAlignment": "RIGHT",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": xp_row_index - 1,
                    "endRowIndex": xp_smooth_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_start_col + total_day_cols,
                },
                "cell": {
                    "userEnteredFormat": {
                        "numberFormat": {"type": "NUMBER", "pattern": ";;;"},
                        "textFormat": {"foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
                    }
                },
                "fields": "userEnteredFormat(numberFormat,textFormat)",
            }
        },
    ]

    # KPI cards background + border
    for col in kpi_starts:
        if col + kpi_span <= ncols:
            format_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 2,
                            "startColumnIndex": col,
                            "endColumnIndex": col + kpi_span,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": kpi_bg}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            format_requests.append(
                {
                    "updateBorders": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 2,
                            "startColumnIndex": col,
                            "endColumnIndex": col + kpi_span,
                        },
                        "top": {"style": "NONE"},
                        "bottom": {"style": "NONE"},
                        "left": {"style": "NONE"},
                        "right": {"style": "NONE"},
                    }
                }
            )

    # Weekly progress KPI gets a softer bar background
    if len(kpi_starts) >= 3:
        prog_col = kpi_starts[2]
        if prog_col + kpi_span <= ncols:
            format_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": prog_col,
                            "endColumnIndex": prog_col + kpi_span,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": kpi_bar_bg}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )
            format_requests.append(
                {
                    "updateBorders": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": 2,
                            "startColumnIndex": prog_col,
                            "endColumnIndex": prog_col + kpi_span,
                        },
                        "top": {"style": "SOLID", "width": 1, "color": border_color},
                        "bottom": {"style": "SOLID", "width": 1, "color": border_color},
                        "left": {"style": "SOLID", "width": 1, "color": border_color},
                        "right": {"style": "SOLID", "width": 1, "color": border_color},
                    }
                }
            )

    # Top bar outer border
    format_requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": topbar_end_col,
                },
                "top": {"style": "NONE"},
                "bottom": {"style": "NONE"},
                "left": {"style": "NONE"},
                "right": {"style": "NONE"},
                "innerHorizontal": {"style": "NONE"},
                "innerVertical": {"style": "NONE"},
            }
        }
    )
    format_requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 2,
                    "startColumnIndex": 0,
                    "endColumnIndex": topbar_end_col,
                },
                "top": {"style": "SOLID", "width": 1, "color": card_border_color},
                "bottom": {"style": "SOLID", "width": 1, "color": card_border_color},
                "left": {"style": "SOLID", "width": 1, "color": card_border_color},
                "right": {"style": "SOLID", "width": 1, "color": card_border_color},
                "innerHorizontal": {"style": "NONE"},
                "innerVertical": {"style": "NONE"},
            }
        }
    )
    format_requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": days_row_index,
                    "startColumnIndex": 0,
                    "endColumnIndex": topbar_end_col,
                },
                "top": {"style": "SOLID", "width": 1, "color": card_border_color},
                "bottom": {"style": "SOLID", "width": 1, "color": card_border_color},
                "left": {"style": "SOLID", "width": 1, "color": card_border_color},
                "right": {"style": "SOLID", "width": 1, "color": card_border_color},
                "innerHorizontal": {"style": "NONE"},
                "innerVertical": {"style": "NONE"},
            }
        }
    )

    # Name column soft background
    if data_rows > 0:
        format_requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": data_start_row - 1,
                        "endRowIndex": data_block_end,
                        "startColumnIndex": name_col,
                        "endColumnIndex": name_col + 1,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": name_bg}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )

    # Progress + chart panel background
    format_requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": progress_row_index - 1,
                    "endRowIndex": days_row_index,
                    "startColumnIndex": 0,
                    "endColumnIndex": day_end_col,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": panel_bg}},
                "fields": "userEnteredFormat.backgroundColor",
            }
        }
    )

    # Progress row typography
    format_requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": progress_row_index - 1,
                    "endRowIndex": missing_row_index,
                    "startColumnIndex": name_col,
                    "endColumnIndex": name_col + 1,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "fontSize": 9},
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        }
    )
    format_requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": progress_row_index - 1,
                    "endRowIndex": missing_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 8,
                            "foregroundColor": {"red": 0.42, "green": 0.42, "blue": 0.42},
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        }
    )
    format_requests.append(
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": progress_row_index - 1,
                    "endRowIndex": progress_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_end_col,
                },
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {
                            "fontSize": 8,
                            "foregroundColor": {"red": 0.36, "green": 0.36, "blue": 0.36},
                        },
                        "horizontalAlignment": "CENTER",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
            }
        }
    )

    # Analysis block background for data rows
    if data_rows > 0:
        format_requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": data_start_row - 1,
                        "endRowIndex": data_block_end,
                        "startColumnIndex": analysis_start_col,
                        "endColumnIndex": analysis_start_col + analysis_cols,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": analysis_bg,
                            "textFormat": {"fontSize": 8},
                            "horizontalAlignment": "CENTER",
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)",
                }
            }
        )
        format_requests.append(
            {
                "updateBorders": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": data_start_row - 1,
                        "endRowIndex": data_block_end,
                        "startColumnIndex": analysis_start_col,
                        "endColumnIndex": analysis_start_col + analysis_cols,
                    },
                    "top": {"style": "SOLID", "width": 1, "color": border_color},
                    "bottom": {"style": "SOLID", "width": 1, "color": border_color},
                    "left": {"style": "SOLID", "width": 1, "color": border_color},
                    "right": {"style": "SOLID", "width": 1, "color": border_color},
                    "innerHorizontal": {"style": "SOLID", "width": 1, "color": border_color},
                    "innerVertical": {"style": "SOLID", "width": 1, "color": border_color},
                }
            }
        )

    # Chart panel border
    format_requests.append(
        {
            "updateBorders": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": chart_start_row_index - 1,
                    "endRowIndex": chart_end_row_index,
                    "startColumnIndex": day_start_col,
                    "endColumnIndex": day_end_col,
                },
                "top": {"style": "SOLID", "width": 1, "color": border_color},
                "bottom": {"style": "SOLID", "width": 1, "color": border_color},
                "left": {"style": "SOLID", "width": 1, "color": border_color},
                "right": {"style": "SOLID", "width": 1, "color": border_color},
            }
        }
    )

    # Week header background colors
    for week in range(week_count):
        color = week_palette[week % len(week_palette)]
        start_col = day_start_col + week * 7
        format_requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 3,
                        "endRowIndex": 5,
                        "startColumnIndex": start_col,
                        "endColumnIndex": start_col + 7,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )

    # Week body background colors
    if data_rows > 0:
        for week in range(week_count):
            color = week_body_palette[week % len(week_body_palette)]
            start_col = day_start_col + week * 7
            format_requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": data_start_row - 1,
                            "endRowIndex": data_block_end,
                            "startColumnIndex": start_col,
                            "endColumnIndex": start_col + 7,
                        },
                        "cell": {"userEnteredFormat": {"backgroundColor": color}},
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            )

    conditional_rules = []
    grid_range = {
        "sheetId": sheet_id,
        "startRowIndex": data_start_row - 1,
        "endRowIndex": (data_end_row + 1) if data_end_row >= data_start_row else data_start_row,
        "startColumnIndex": day_start_col,
        "endColumnIndex": day_start_col + total_day_cols,
    }
    if data_rows > 0:
        helper_start_letter = _col_to_a1(helper_start_col + 1)
        helper_end_letter = _col_to_a1(helper_start_col + helper_cols)
        helper_range = f"${helper_start_letter}${data_start_row}:${helper_end_letter}${data_end_row}"
        row_offset = data_start_row - 1
        col_offset = day_start_col
        formula_sep = arg_sep
        thr_high = _format_decimal(0.75)
        thr_mid = _format_decimal(0.4)
        thr_low = _format_decimal(0.0)

        conditional_rules.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [
                                    {
                                        "userEnteredValue": (
                                            f"=INDEX({helper_range}{formula_sep}ROW()-{row_offset}{formula_sep}COLUMN()-{col_offset})>{thr_high}"
                                        )
                                    }
                                ],
                            },
                            "format": {
                                "backgroundColor": {"red": 0.63, "green": 0.78, "blue": 0.63}
                            },
                        },
                    },
                    "index": 0,
                }
            }
        )
        conditional_rules.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [
                                    {
                                        "userEnteredValue": (
                                            f"=INDEX({helper_range}{formula_sep}ROW()-{row_offset}{formula_sep}COLUMN()-{col_offset})>{thr_mid}"
                                        )
                                    }
                                ],
                            },
                            "format": {
                                "backgroundColor": {"red": 0.76, "green": 0.86, "blue": 0.74}
                            },
                        },
                    },
                    "index": 0,
                }
            }
        )
        conditional_rules.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": {
                                "type": "CUSTOM_FORMULA",
                                "values": [
                                    {
                                        "userEnteredValue": (
                                            f"=INDEX({helper_range}{formula_sep}ROW()-{row_offset}{formula_sep}COLUMN()-{col_offset})>{thr_low}"
                                        )
                                    }
                                ],
                            },
                            "format": {
                                "backgroundColor": {"red": 0.86, "green": 0.92, "blue": 0.84}
                            },
                        },
                    },
                    "index": 0,
                }
            }
        )

    # Chart for progress row
    chart_requests = []
    if tracker_objs:
        chart_width = total_day_cols * day_col_px + 8
        chart_height = chart_row_count * chart_row_height
        chart_requests.append(
            {
                "addChart": {
                    "chart": {
                        "spec": {
                            "title": "",
                                "basicChart": {
                                    "chartType": "AREA",
                                    "legendPosition": "NO_LEGEND",
                                    "axis": [
                                        {"position": "BOTTOM_AXIS", "title": ""},
                                        {
                                        "position": "LEFT_AXIS",
                                        "title": "XP",
                                        "viewWindowOptions": {
                                            "viewWindowMin": 0,
                                            "viewWindowMax": xp_axis_max,
                                        },
                                    },
                                ],
                                "domains": [
                                    {
                                        "domain": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": sheet_id,
                                                        "startRowIndex": days_row_index - 1,
                                                        "endRowIndex": days_row_index,
                                                        "startColumnIndex": day_start_col,
                                                        "endColumnIndex": day_start_col + total_day_cols,
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                ],
                                "series": [
                                    {
                                        "series": {
                                            "sourceRange": {
                                                "sources": [
                                                    {
                                                        "sheetId": sheet_id,
                                                        "startRowIndex": xp_smooth_row_index - 1,
                                                        "endRowIndex": xp_smooth_row_index,
                                                        "startColumnIndex": day_start_col,
                                                        "endColumnIndex": day_start_col + total_day_cols,
                                                    }
                                                ]
                                            }
                                        },
                                        "targetAxis": "LEFT_AXIS",
                                        "color": {"red": 0.93, "green": 0.79, "blue": 0.81},
                                    }
                                ],
                                "headerCount": 0,
                            },
                        },
                        "position": {
                            "overlayPosition": {
                                "anchorCell": {
                                    "sheetId": sheet_id,
                                    "rowIndex": chart_start_row_index - 1,
                                    "columnIndex": day_start_col,
                                },
                                "widthPixels": chart_width,
                                "heightPixels": chart_height,
                            }
                        },
                    }
                }
            }
        )

    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                *chart_delete_requests,
                *cf_delete_requests,
                *format_requests,
                *conditional_rules,
                *chart_requests,
            ]
        },
    ).execute()

    # Apply checkbox validation for binary trackers only
    if data_rows > 0:
        binary_rows = [
            data_start_row + idx
            for idx, tracker in enumerate(tracker_objs)
            if tracker.type == "binary"
        ]
        if binary_rows:
            binary_rows.sort()
            ranges = []
            start = prev = binary_rows[0]
            for row in binary_rows[1:]:
                if row == prev + 1:
                    prev = row
                    continue
                ranges.append((start, prev))
                start = prev = row
            ranges.append((start, prev))
            dv_requests = []
            for start_row, end_row in ranges:
                dv_requests.append(
                    {
                        "setDataValidation": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": day_start_col,
                                "endColumnIndex": day_start_col + total_day_cols,
                            },
                            "rule": {
                                "condition": {"type": "BOOLEAN"},
                                "showCustomUi": True,
                                "strict": True,
                            },
                        }
                    }
                )
            if dv_requests:
                sheets.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id, body={"requests": dv_requests}
                ).execute()


def _sync_monthly_demo(
    sheets,
    spreadsheet_id: str,
    sheet_map: dict,
    today: dt.date,
    count_fn: str,
    avg_fn: str,
    arg_sep: str,
    tracker_objs: list[Tracker],
    logs_by_tracker: dict[int, list[tuple[dt.date, float, bool]]],
) -> None:
    sum_fn = "СУММ" if count_fn == "СЧЁТ" else "SUM"
    title = "Ежемесячник — демо"
    sheet_id = sheet_map.get(title)
    if sheet_id is None:
        resp = sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
        ).execute()
        sheet_id = resp["replies"][0]["addSheet"]["properties"]["sheetId"]

    month_label = [
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ][today.month - 1]
    month_title = f"{month_label.capitalize()} {today.year}"

    trackers = [(t.id, t.name, t.type) for t in tracker_objs]
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]

    ncols = 11
    clear_cols = 26
    def pad_row(values: list) -> list:
        return values + [""] * (ncols - len(values))

    rows = []
    rows.append(pad_row([f"Ежемесячник — {month_title} (демо)"]))
    rows.append(pad_row(["Месяц:", month_title]))
    rows.append(pad_row([]))

    week_header_rows = []
    table_header_rows = []
    separator_rows = []
    data_row_ranges = []
    week_header_color_ranges = []
    week_body_color_ranges = []
    current_row = len(rows) + 1

    start_month = today.replace(day=1)
    if start_month.month == 12:
        end_month = start_month.replace(year=start_month.year + 1, month=1, day=1) - dt.timedelta(days=1)
    else:
        end_month = start_month.replace(month=start_month.month + 1, day=1) - dt.timedelta(days=1)

    week_ranges = []
    cursor = start_month
    for _ in range(4):
        end = min(cursor + dt.timedelta(days=6), end_month)
        week_ranges.append((cursor, end))
        cursor = cursor + dt.timedelta(days=7)

    goals_by_tracker = {
        tracker_id: _get_tracker_goals(tracker_id) for tracker_id, _name, _ttype in trackers
    }
    daily_by_tracker: dict[int, dict[dt.date, list[float]]] = {}
    for tracker_id, _name, _ttype in trackers:
        daily = {}
        for date, value, _partial in logs_by_tracker.get(tracker_id, []):
            if date < start_month or date > end_month:
                continue
            daily.setdefault(date, []).append(value)
        daily_by_tracker[tracker_id] = daily

    use_ru = count_fn == "СЧЁТ"
    progress_col = 9

    separator_color = {"red": 0.98, "green": 0.98, "blue": 0.98}
    week_header_palette = {
        1: {"red": 0.73, "green": 0.85, "blue": 0.69},
        2: {"red": 0.70, "green": 0.80, "blue": 0.84},
        3: {"red": 0.80, "green": 0.74, "blue": 0.88},
        4: {"red": 0.93, "green": 0.78, "blue": 0.64},
    }
    week_body_palette = {
        1: {"red": 0.86, "green": 0.93, "blue": 0.82},
        2: {"red": 0.83, "green": 0.89, "blue": 0.91},
        3: {"red": 0.90, "green": 0.87, "blue": 0.94},
        4: {"red": 0.96, "green": 0.88, "blue": 0.80},
    }
    type_labels = {
        "count": "счет",
        "time": "время",
        "binary": "бинарный",
        "scale": "шкала",
    }

    def _format_goal(value: float) -> str:
        if value.is_integer():
            return str(int(value))
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text.replace(".", ",") if use_ru else text

    def _daily_display(ttype: str, values: list[float]) -> Optional[float]:
        if not values:
            return None
        if ttype == "scale":
            return sum(values) / len(values)
        if ttype == "binary":
            return 1.0 if any(v >= 1 for v in values) else 0.0
        return float(sum(values))

    for week_idx, (week_start, week_end) in enumerate(week_ranges, start=1):
        week_dates = [week_start + dt.timedelta(days=i) for i in range(7)]
        week_header_rows.append(current_row)
        header_row = [""] * ncols
        header_row[0] = f"Неделя {week_idx} ({week_start:%d.%m}–{week_end:%d.%m})"
        rows.append(header_row)
        table_header_rows.append(current_row + 1)
        rows.append(
            pad_row(
                ["Привычка", "Тип"] + days + ["Итог недели %", "Цель (неделя)"]
            )
        )
        current_row += 2
        data_start = current_row
        for tracker_id, name, ttype in trackers:
            daily_map = daily_by_tracker.get(tracker_id, {})
            goals = goals_by_tracker.get(tracker_id, {})
            week_goal = float(goals.get("week") or 0)
            week_goal_display = int(week_goal) if week_goal and week_goal.is_integer() else week_goal
            display_values = []
            for date in week_dates:
                if date > end_month:
                    display_values.append("")
                    continue
                value = _daily_display(ttype, daily_map.get(date, []))
                display_values.append("" if value is None else value)
            if week_goal > 0:
                goal_literal = _format_goal(week_goal)
                if ttype == "scale":
                    progress = (
                        f"=IF({count_fn}(C{current_row}:I{current_row})=0{arg_sep}"""
                        f"{arg_sep}MIN(1{arg_sep}{avg_fn}(C{current_row}:I{current_row})/{goal_literal}))"
                    )
                else:
                    progress = (
                        f"=IF({count_fn}(C{current_row}:I{current_row})=0{arg_sep}"""
                        f"{arg_sep}MIN(1{arg_sep}{sum_fn}(C{current_row}:I{current_row})/{goal_literal}))"
                    )
            else:
                progress = ""
            type_label = type_labels.get(ttype, ttype)
            rows.append(
                pad_row([name, type_label] + display_values + [progress, week_goal_display or ""])
            )
            current_row += 1
        data_end = current_row - 1
        if data_end >= data_start:
            data_row_ranges.append((data_start, data_end))
            header_color = week_header_palette.get(week_idx)
            body_color = week_body_palette.get(week_idx)
            if header_color:
                week_header_color_ranges.append((week_header_rows[-1], header_color))
            if body_color:
                week_body_color_ranges.append((table_header_rows[-1], data_end, body_color))
        rows.append(pad_row([]))
        separator_rows.append(current_row)
        current_row += 1

    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A:Z",
    ).execute()

    last_col = _col_to_a1(ncols)
    sheets.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=f"{title}!A1:{last_col}{len(rows)}",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()

    chart_delete_requests = []
    sheet_info = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties,charts)",
    ).execute()
    for sheet in sheet_info.get("sheets", []):
        props = sheet.get("properties", {})
        if props.get("sheetId") != sheet_id:
            continue
        for chart in sheet.get("charts", []):
            chart_id = chart.get("chartId")
            if chart_id is not None:
                chart_delete_requests.append(
                    {"deleteEmbeddedObject": {"objectId": chart_id}}
                )

    end_row = len(rows)
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                *chart_delete_requests,
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": end_row,
                            "startColumnIndex": 0,
                            "endColumnIndex": clear_cols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": ncols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "textFormat": {"bold": True, "fontSize": 12},
                                "horizontalAlignment": "LEFT",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
                    }
                },
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row - 1,
                                "endRowIndex": row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
                        }
                    }
                    for row in week_header_rows
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row - 1,
                                "endRowIndex": row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": True},
                                    "horizontalAlignment": "CENTER",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
                        }
                    }
                    for row in table_header_rows
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row - 1,
                                "endRowIndex": row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color,
                                }
                            },
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                    for row, color in week_header_color_ranges
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color,
                                }
                            },
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                    for start_row, end_row, color in week_body_color_ranges
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row - 1,
                                "endRowIndex": row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": separator_color,
                                }
                            },
                            "fields": "userEnteredFormat.backgroundColor",
                        }
                    }
                    for row in separator_rows
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": 0,
                                "endColumnIndex": ncols,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "textFormat": {"bold": False},
                                }
                            },
                            "fields": "userEnteredFormat.textFormat",
                        }
                    }
                    for start_row, end_row in data_row_ranges
                ],
                *[
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": start_row - 1,
                                "endRowIndex": end_row,
                                "startColumnIndex": 0,
                                "endColumnIndex": 2,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "horizontalAlignment": "LEFT",
                                    "verticalAlignment": "MIDDLE",
                                }
                            },
                            "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
                        }
                    }
                    for start_row, end_row in data_row_ranges
                ],
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2,
                            "endRowIndex": end_row,
                            "startColumnIndex": 2,
                            "endColumnIndex": ncols,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "horizontalAlignment": "CENTER",
                                "verticalAlignment": "MIDDLE",
                            }
                        },
                        "fields": "userEnteredFormat(horizontalAlignment,verticalAlignment)",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2,
                            "endRowIndex": end_row,
                            "startColumnIndex": 9,
                            "endColumnIndex": 10,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "PERCENT", "pattern": "0%"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2,
                            "endRowIndex": end_row,
                            "startColumnIndex": 2,
                            "endColumnIndex": 9,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "NUMBER", "pattern": "0.0"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 2,
                            "endRowIndex": end_row,
                            "startColumnIndex": 10,
                            "endColumnIndex": 11,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": "NUMBER", "pattern": "0"}
                            }
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": ncols,
                        },
                        "properties": {
                            "pixelSize": 90,
                        },
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 0,
                            "endIndex": 1,
                        },
                        "properties": {"pixelSize": 220},
                        "fields": "pixelSize",
                    }
                },
                {
                    "updateDimensionProperties": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "COLUMNS",
                            "startIndex": 9,
                            "endIndex": 11,
                        },
                        "properties": {"pixelSize": 110},
                        "fields": "pixelSize",
                    }
                },
                *[
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet_id,
                                "dimension": "ROWS",
                                "startIndex": row - 1,
                                "endIndex": row,
                            },
                            "properties": {"pixelSize": 21, "hiddenByUser": False},
                            "fields": "pixelSize,hiddenByUser",
                        }
                    }
                    for row in separator_rows
                ],
            ]
        },
    ).execute()

def create_spreadsheet_from_template(user_tg_id: int) -> Tuple[str, str]:
    template = _template_path()
    if not template.exists():
        return create_blank_spreadsheet(user_tg_id)

    parent_id = _drive_parent_id()
    drive = _drive_client()
    media = MediaFileUpload(
        str(template),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=False,
    )
    body = {
        "name": f"Habitbot {user_tg_id}",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    if parent_id:
        body["parents"] = [parent_id]
    created = (
        drive.files()
        .create(
            body=body,
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=bool(parent_id),
        )
        .execute()
    )
    sheet_id = created["id"]
    url = created.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    return sheet_id, url


def create_spreadsheet_from_template_with_credentials(
    user_tg_id: int, creds: Credentials
) -> Tuple[str, str]:
    template = _template_path()
    if not template.exists():
        return create_blank_spreadsheet_with_credentials(user_tg_id, creds)

    drive = _drive_client_for_user(creds)
    media = MediaFileUpload(
        str(template),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=False,
    )
    body = {
        "name": f"Habitbot {user_tg_id}",
        "mimeType": "application/vnd.google-apps.spreadsheet",
    }
    created = (
        drive.files()
        .create(body=body, media_body=media, fields="id, webViewLink")
        .execute()
    )
    sheet_id = created["id"]
    url = created.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{sheet_id}"
    return sheet_id, url


def create_blank_spreadsheet(user_tg_id: int) -> Tuple[str, str]:
    sheets = _sheets_client()
    body = {
        "properties": {"title": f"Habitbot {user_tg_id}"},
        "sheets": [
            {"properties": {"title": "Habits Tracker 2026"}},
            {"properties": {"title": "raw_trackers"}},
            {"properties": {"title": "raw_tracker_goals"}},
            {"properties": {"title": "raw_tracker_logs"}},
            {"properties": {"title": JOURNAL_SHEET_TITLE}},
        ],
    }
    created = sheets.spreadsheets().create(body=body, fields="spreadsheetId,spreadsheetUrl").execute()
    spreadsheet_id = created["spreadsheetId"]
    parent_id = _drive_parent_id()
    if parent_id:
        drive = _drive_client()
        drive.files().update(
            fileId=spreadsheet_id,
            addParents=parent_id,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()
    return spreadsheet_id, created["spreadsheetUrl"]


def create_blank_spreadsheet_with_credentials(
    user_tg_id: int, creds: Credentials
) -> Tuple[str, str]:
    sheets = _sheets_client_for_user(creds)
    body = {
        "properties": {"title": f"Habitbot {user_tg_id}"},
        "sheets": [
            {"properties": {"title": "Habits Tracker 2026"}},
            {"properties": {"title": "raw_trackers"}},
            {"properties": {"title": "raw_tracker_goals"}},
            {"properties": {"title": "raw_tracker_logs"}},
            {"properties": {"title": JOURNAL_SHEET_TITLE}},
        ],
    }
    created = sheets.spreadsheets().create(
        body=body, fields="spreadsheetId,spreadsheetUrl"
    ).execute()
    return created["spreadsheetId"], created["spreadsheetUrl"]


def share_sheet(spreadsheet_id: str, email: str) -> None:
    drive = _drive_client()
    drive.permissions().create(
        fileId=spreadsheet_id,
        body={"type": "user", "role": "writer", "emailAddress": email},
        sendNotificationEmail=False,
        supportsAllDrives=True,
    ).execute()


def _rows_to_values(rows: Iterable[tuple]) -> list[list]:
    return [[*row] for row in rows]


def _build_raw_data(user_id: int) -> tuple[list[list], list[list], list[list]]:
    with db_session() as session:
        trackers = (
            session.query(Tracker)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(Tracker.order_index, Tracker.id)
            .all()
        )
        goals = (
            session.query(TrackerGoal)
            .join(Tracker, TrackerGoal.tracker_id == Tracker.id)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(TrackerGoal.tracker_id, TrackerGoal.period)
            .all()
        )
        logs = (
            session.query(TrackerLog)
            .join(Tracker, TrackerLog.tracker_id == Tracker.id)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(TrackerLog.date, TrackerLog.tracker_id, TrackerLog.id)
            .all()
        )

    tracker_rows = []
    for t in trackers:
        target_day = t.target if t.period == "day" and t.target else ""
        tracker_rows.append(
            (
                t.id,
                t.name,
                t.type,
                t.unit or "",
                t.xp,
                target_day,
                bool(t.active),
                t.streak_mode or "activity",
            )
        )

    goal_rows = [(g.tracker_id, g.period, g.target) for g in goals]
    log_rows = [
        (l.id, l.tracker_id, l.date.isoformat(), float(l.value), bool(l.partial)) for l in logs
    ]

    return _rows_to_values(tracker_rows), _rows_to_values(goal_rows), _rows_to_values(log_rows)


def _ensure_journal_sheet(sheets, spreadsheet_id: str) -> None:
    meta = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(title))",
    ).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    if JOURNAL_SHEET_TITLE in existing:
        return
    sheets.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": JOURNAL_SHEET_TITLE}}}]},
    ).execute()


def _build_journal_rows(user_id: int) -> list[list]:
    with db_session() as session:
        entries = (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id)
            .order_by(JournalEntry.date.asc())
            .all()
        )
        reports = (
            session.query(JournalWeeklyReport)
            .filter(JournalWeeklyReport.user_id == user_id)
            .order_by(JournalWeeklyReport.week_start.asc())
            .all()
        )

    rows_with_sort = []
    for entry in entries:
        text = (entry.text or "").strip()
        if not text:
            continue
        created = entry.updated_at or entry.created_at
        created_str = created.isoformat() if created else ""
        row = [
            "daily",
            entry.date.isoformat(),
            "",
            "",
            text,
            created_str,
        ]
        rows_with_sort.append((entry.date, row))

    for report in reports:
        text = (report.analysis_text or "").strip()
        if not text:
            continue
        created_str = report.created_at.isoformat() if report.created_at else ""
        row = [
            "weekly",
            "",
            report.week_start.isoformat(),
            report.week_end.isoformat(),
            text,
            created_str,
        ]
        rows_with_sort.append((report.week_end, row))

    rows_with_sort.sort(key=lambda item: item[0])
    return [row for _sort_key, row in rows_with_sort]


def push_journal_data(spreadsheet_id: str, user_id: int) -> None:
    sheets = _sheets_client()
    _ensure_journal_sheet(sheets, spreadsheet_id)
    rows = _build_journal_rows(user_id)
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"{JOURNAL_SHEET_TITLE}!A:Z",
    ).execute()
    data = [
        {
            "range": f"{JOURNAL_SHEET_TITLE}!A1:F",
            "values": [
                ["type", "date", "week_start", "week_end", "text", "created_at"],
                *rows,
            ],
        }
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


def push_journal_data_with_credentials(
    spreadsheet_id: str, user_id: int, creds: Credentials
) -> None:
    sheets = _sheets_client_for_user(creds)
    _ensure_journal_sheet(sheets, spreadsheet_id)
    rows = _build_journal_rows(user_id)
    sheets.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=f"{JOURNAL_SHEET_TITLE}!A:Z",
    ).execute()
    data = [
        {
            "range": f"{JOURNAL_SHEET_TITLE}!A1:F",
            "values": [
                ["type", "date", "week_start", "week_end", "text", "created_at"],
                *rows,
            ],
        }
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()


def push_raw_data(spreadsheet_id: str, user_id: int) -> None:
    trackers, goals, logs = _build_raw_data(user_id)
    sheets = _sheets_client()

    data = [
        {
            "range": "raw_trackers!A1:H",
            "values": [
                ["id", "name", "type", "unit", "xp", "target_day", "active", "streak_mode"],
                *trackers,
            ],
        },
        {
            "range": "raw_tracker_goals!A1:C",
            "values": [["tracker_id", "period", "target"], *goals],
        },
        {
            "range": "raw_tracker_logs!A1:E",
            "values": [["id", "tracker_id", "date", "value", "partial"], *logs],
        },
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    push_journal_data(spreadsheet_id, user_id)


def push_raw_data_with_credentials(
    spreadsheet_id: str, user_id: int, creds: Credentials
) -> None:
    trackers, goals, logs = _build_raw_data(user_id)
    sheets = _sheets_client_for_user(creds)

    data = [
        {
            "range": "raw_trackers!A1:H",
            "values": [
                ["id", "name", "type", "unit", "xp", "target_day", "active", "streak_mode"],
                *trackers,
            ],
        },
        {
            "range": "raw_tracker_goals!A1:C",
            "values": [["tracker_id", "period", "target"], *goals],
        },
        {
            "range": "raw_tracker_logs!A1:E",
            "values": [["id", "tracker_id", "date", "value", "partial"], *logs],
        },
    ]
    sheets.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    push_journal_data_with_credentials(spreadsheet_id, user_id, creds)


def create_user_sheet(user_id: int, user_tg_id: int, email: str) -> tuple[str, str]:
    spreadsheet_id, url = create_spreadsheet_from_template(user_tg_id)
    _set_spreadsheet_timezone(spreadsheet_id, user_id)
    share_sheet(spreadsheet_id, email)
    push_raw_data(spreadsheet_id, user_id)
    sync_habits_grid(spreadsheet_id, user_id, delete_setup=True)
    return spreadsheet_id, url


def create_user_sheet_with_credentials(
    user_id: int, user_tg_id: int, creds: Credentials
) -> tuple[str, str]:
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    spreadsheet_id, url = create_spreadsheet_from_template_with_credentials(user_tg_id, creds)
    _set_spreadsheet_timezone(spreadsheet_id, user_id, creds)
    push_raw_data_with_credentials(spreadsheet_id, user_id, creds)
    sync_habits_grid_with_credentials(spreadsheet_id, user_id, creds, delete_setup=True)
    return spreadsheet_id, url


def connect_existing_sheet(spreadsheet_id: str, user_id: int) -> tuple[str, str]:
    sheets = _sheets_client()
    _set_spreadsheet_timezone(spreadsheet_id, user_id)
    meta = sheets.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="spreadsheetId,spreadsheetUrl,sheets(properties(title))",
    ).execute()
    existing = {s["properties"]["title"] for s in meta.get("sheets", [])}
    required = {"raw_trackers", "raw_tracker_goals", "raw_tracker_logs", JOURNAL_SHEET_TITLE}
    requests = [
        {"addSheet": {"properties": {"title": title}}}
        for title in sorted(required - existing)
    ]
    if requests:
        sheets.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()
    push_raw_data(spreadsheet_id, user_id)
    sync_habits_grid(spreadsheet_id, user_id, delete_setup=False)
    url = meta.get("spreadsheetUrl") or f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
    return spreadsheet_id, url
