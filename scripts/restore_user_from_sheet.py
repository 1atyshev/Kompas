#!/usr/bin/env python3
import argparse
import csv
import datetime as dt
import io
import json
import sqlite3
import urllib.parse
import urllib.request
from typing import Optional


JOURNAL_SHEET = "\u0414\u043d\u0435\u0432\u043d\u0438\u043a"


def _sheet_id_from_url(url: str) -> str:
    if "/d/" not in url:
        return url
    parts = url.split("/d/", 1)[1].split("/", 1)
    return parts[0]


def _fetch_csv_rows(sheet_id: str, sheet_name: str) -> list[dict[str, str]]:
    url = (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        f"tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}"
    )
    with urllib.request.urlopen(url, timeout=20) as resp:
        data = resp.read()
    text = data.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "y", "да"):
        return True
    if raw in ("0", "false", "no", "n", "нет"):
        return False
    return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def _parse_date(value: Optional[str]) -> Optional[dt.date]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        return None


def _xp_needed(level: int) -> int:
    if level < 1:
        level = 1
    return int(100 + 15 * (level - 1) + ((level - 1) ** 1.35) * 5)


def _load_count_xp_map(raw: Optional[str]) -> dict[int, int]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[int, int] = {}
    for key, value in data.items():
        try:
            result[int(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _tracker_xp_for_value(tracker: dict, value: float, partial: bool = False) -> int:
    if value <= 0:
        return 0
    ttype = tracker.get("type") or ""
    xp = int(tracker.get("xp") or 0)
    if ttype == "binary":
        if partial:
            return max(1, xp // 2) if xp else 0
        return max(1, xp) if xp else 0
    if ttype == "time":
        earned = int(value * xp)
        return max(1, earned) if value > 0 else 0
    if ttype == "count":
        mapping = _load_count_xp_map(tracker.get("xp_count_map"))
        if mapping:
            if float(value).is_integer():
                return int(mapping.get(int(value), 0))
            return 0
        fallback = min(xp, 10) if xp else 0
        return max(1, fallback) if fallback else 0
    if ttype == "scale":
        xp_min = tracker.get("xp_scale_min")
        xp_max = tracker.get("xp_scale_max")
        if xp_min is not None and xp_max is not None:
            v = max(1.0, min(10.0, float(value)))
            earned = xp_min + (v - 1) * (xp_max - xp_min) / 9
            return int(round(earned))
        fallback = min(xp, 10) if xp else 0
        return max(1, fallback) if fallback else 0
    return max(1, xp) if xp else 0


def _compute_level(total_xp: int) -> tuple[int, int]:
    lvl = 1
    xp = total_xp
    while xp >= _xp_needed(lvl):
        xp -= _xp_needed(lvl)
        lvl += 1
    return lvl, xp


def _compute_streak(dates: set[dt.date]) -> tuple[int, Optional[dt.date]]:
    if not dates:
        return 0, None
    last_date = max(dates)
    streak = 1
    cursor = last_date - dt.timedelta(days=1)
    while cursor in dates:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak, last_date


def restore_user(db_path: str, tg_id: int, sheet_id: str, set_google_link: bool) -> None:
    trackers_rows = _fetch_csv_rows(sheet_id, "raw_trackers")
    goals_rows = _fetch_csv_rows(sheet_id, "raw_tracker_goals")
    logs_rows = _fetch_csv_rows(sheet_id, "raw_tracker_logs")
    journal_rows = _fetch_csv_rows(sheet_id, JOURNAL_SHEET)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT id FROM users WHERE tg_id = ?", (tg_id,))
    row = cur.fetchone()
    if not row:
        raise SystemExit(f"user with tg_id={tg_id} not found")
    user_id = int(row["id"])

    tracker_ids = [r[0] for r in cur.execute("SELECT id FROM trackers WHERE user_id = ?", (user_id,))]
    if tracker_ids:
        placeholders = ",".join("?" * len(tracker_ids))
        cur.execute(f"DELETE FROM tracker_logs WHERE tracker_id IN ({placeholders})", tracker_ids)
        cur.execute(f"DELETE FROM tracker_goals WHERE tracker_id IN ({placeholders})", tracker_ids)
        cur.execute(
            f"DELETE FROM tracker_goal_display WHERE tracker_id IN ({placeholders})",
            tracker_ids,
        )
    cur.execute("DELETE FROM trackers WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM missions WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM journal_messages WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM journal_entries WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM journal_weekly_reports WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM coach_messages WHERE user_id = ?", (user_id,))

    tracker_map: dict[int, int] = {}
    tracker_payloads: list[dict] = []
    for idx, row in enumerate(trackers_rows):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        old_id = _parse_int(row.get("id"))
        ttype = (row.get("type") or "binary").strip()
        unit = (row.get("unit") or "").strip()
        xp = _parse_int(row.get("xp")) or 0
        target_day = _parse_int(row.get("target_day")) or 0
        active = _parse_bool(row.get("active"))
        streak_mode = (row.get("streak_mode") or "activity").strip() or "activity"
        streak_period = (row.get("streak_period") or "day").strip() or "day"
        streak_min_value = _parse_float(row.get("streak_min_value")) or 0.0
        streak_partial_ok = _parse_bool(row.get("streak_partial_ok"))
        if streak_partial_ok is None:
            streak_partial_ok = True
        xp_count_map = row.get("xp_count_map") or None
        xp_scale_min = _parse_int(row.get("xp_scale_min"))
        xp_scale_max = _parse_int(row.get("xp_scale_max"))

        cur.execute(
            """
            INSERT INTO trackers (
                user_id, name, type, unit, xp, target, period, active, order_index, days,
                streak_enabled, streak_mode, streak_period, streak_min_value, streak_partial_ok,
                xp_count_map, xp_scale_min, xp_scale_max
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                name,
                ttype,
                unit,
                xp,
                target_day,
                "day",
                True if active is None else active,
                idx,
                "",
                True,
                streak_mode,
                streak_period,
                streak_min_value,
                streak_partial_ok,
                xp_count_map,
                xp_scale_min,
                xp_scale_max,
            ),
        )
        new_id = cur.lastrowid
        if old_id is not None:
            tracker_map[old_id] = new_id
        tracker_payloads.append(
            {
                "id": new_id,
                "type": ttype,
                "xp": xp,
                "xp_count_map": xp_count_map,
                "xp_scale_min": xp_scale_min,
                "xp_scale_max": xp_scale_max,
            }
        )

    for row in goals_rows:
        old_id = _parse_int(row.get("tracker_id"))
        if old_id is None or old_id not in tracker_map:
            continue
        period = (row.get("period") or "").strip()
        target = _parse_float(row.get("target"))
        if not period or target is None:
            continue
        cur.execute(
            "INSERT INTO tracker_goals (tracker_id, period, target) VALUES (?, ?, ?)",
            (tracker_map[old_id], period, target),
        )

    total_xp = 0
    streak_dates: set[dt.date] = set()
    tracker_by_id = {t["id"]: t for t in tracker_payloads}
    for row in logs_rows:
        old_id = _parse_int(row.get("tracker_id"))
        if old_id is None or old_id not in tracker_map:
            continue
        date = _parse_date(row.get("date"))
        value = _parse_float(row.get("value"))
        if date is None or value is None:
            continue
        partial = _parse_bool(row.get("partial")) or False
        tracker_id = tracker_map[old_id]
        cur.execute(
            "INSERT INTO tracker_logs (tracker_id, date, value, partial) VALUES (?, ?, ?, ?)",
            (tracker_id, date.isoformat(), value, partial),
        )
        tracker_payload = tracker_by_id.get(tracker_id)
        if tracker_payload:
            total_xp += _tracker_xp_for_value(tracker_payload, value, partial)
        streak_dates.add(date)

    for row in journal_rows:
        row_type = (row.get("type") or "").strip().lower()
        text = (row.get("text") or "").strip()
        created_at = (row.get("created_at") or "").strip() or None
        if row_type == "daily":
            date = _parse_date(row.get("date"))
            if not date:
                continue
            cur.execute(
                """
                INSERT INTO journal_entries (user_id, date, text, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (user_id, date.isoformat(), text, "closed", created_at, created_at),
            )
        elif row_type == "weekly":
            week_start = _parse_date(row.get("week_start"))
            week_end = _parse_date(row.get("week_end"))
            if not week_start or not week_end:
                continue
            cur.execute(
                """
                INSERT INTO journal_weekly_reports (user_id, week_start, week_end, analysis_text, created_at)
                VALUES (?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (user_id, week_start.isoformat(), week_end.isoformat(), text, created_at),
            )

    level, xp = _compute_level(total_xp)
    streak, last_date = _compute_streak(streak_dates)
    cur.execute(
        "UPDATE users SET level = ?, xp = ?, streak = ?, streak_last_date = ? WHERE id = ?",
        (level, xp, streak, last_date.isoformat() if last_date else None, user_id),
    )

    if set_google_link:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        cur.execute(
            "UPDATE users SET google_sheet_id = ?, google_sheet_url = ? WHERE id = ?",
            (sheet_id, url, user_id),
        )

    conn.commit()
    conn.close()

    print(
        "restore complete:",
        f"trackers={len(tracker_payloads)}",
        f"goals={len(goals_rows)}",
        f"logs={len(logs_rows)}",
        f"journal={len(journal_rows)}",
        f"xp_total={total_xp}",
        f"level={level}",
        f"streak={streak}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="bot.db")
    parser.add_argument("--tg-id", type=int, required=True)
    parser.add_argument("--sheet-id", default=None)
    parser.add_argument("--sheet-url", default=None)
    parser.add_argument("--set-google-link", action="store_true")
    args = parser.parse_args()

    sheet_id = args.sheet_id or (args.sheet_url and _sheet_id_from_url(args.sheet_url))
    if not sheet_id:
        raise SystemExit("sheet id or url required")

    restore_user(args.db_path, args.tg_id, sheet_id, args.set_google_link)


if __name__ == "__main__":
    main()
