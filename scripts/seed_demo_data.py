import datetime as dt
import random
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "bot.db"
DAYS = 30
SEED = 42

random.seed(SEED)

def daterange(start: dt.date, end: dt.date):
    cur = start
    while cur <= end:
        yield cur
        cur += dt.timedelta(days=1)


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        "SELECT id, name, type FROM trackers WHERE active=1 ORDER BY id"
    )
    trackers = cur.fetchall()

    end = dt.date.today()
    start = end - dt.timedelta(days=DAYS - 1)

    tracker_ids = [t["id"] for t in trackers]
    cur.execute(
        "DELETE FROM tracker_logs WHERE tracker_id IN (%s) AND date BETWEEN ? AND ?"
        % ",".join(["?"] * len(tracker_ids)),
        tracker_ids + [start.isoformat(), end.isoformat()],
    )

    # Precompute workout days for a consistent weekly goal: Mon/Wed/Fri
    workout_days = set()
    for d in daterange(start, end):
        if d.weekday() in {0, 2, 4}:
            workout_days.add(d)

    logs = []
    for t in trackers:
        t_id = t["id"]
        name = (t["name"] or "").lower()
        t_type = t["type"]

        for day in daterange(start, end):
            value = None
            partial = 0

            if t_type == "binary":
                # 70% done, 10% partial
                roll = random.random()
                if roll < 0.1:
                    value = 0.5
                    partial = 1
                elif roll < 0.8:
                    value = 1
            elif t_type == "time":
                if day.weekday() < 5:
                    value = random.choice([1, 2, 3, 4, 5, 6])
            elif t_type == "count":
                if "тренир" in name:
                    if day in workout_days:
                        value = 1
                else:
                    value = random.choice([0, 1, 1, 2, 3])
            elif t_type == "scale":
                value = random.choice([4, 5, 6, 7, 8, 9])

            if value is None or value == 0:
                continue

            logs.append((t_id, day.isoformat(), float(value), partial))

    cur.executemany(
        "INSERT INTO tracker_logs (tracker_id, date, value, partial) VALUES (?, ?, ?, ?)",
        logs,
    )

    conn.commit()
    conn.close()
    print(f"Seeded {len(logs)} tracker logs for {start}..{end}")


if __name__ == "__main__":
    main()
