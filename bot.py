from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import tempfile
import time
import traceback
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qsl, urlencode

from aiogram import BaseMiddleware, Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
    User as TgUser,
)
from aiohttp import ClientSession, FormData, web
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from sqlalchemy import case, func, inspect, text

load_dotenv()  # загружаем .env до инициализации движка БД

from db import db_session, engine
from google.oauth2.credentials import Credentials
from models import (
    Base,
    CoachMessage,
    JournalEntry,
    JournalMessage,
    JournalWeeklyReport,
    Mission,
    Tracker,
    TrackerGoal,
    TrackerGoalDisplay,
    TrackerLog,
    User,
)


BOT_TOKEN = os.getenv("BOT_TOKEN")
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
GOOGLE_OAUTH_PORT = int(os.getenv("GOOGLE_OAUTH_PORT", "8080"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
DEEPSEEK_API_BASE = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEEPSEEK_CHAT_MODEL = os.getenv("DEEPSEEK_CHAT_MODEL", "deepseek-chat")
OPENAI_AUDIO_MODEL = os.getenv("OPENAI_AUDIO_MODEL", "whisper-1")
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "").strip().rstrip("/")
WEB_ANALYTICS_PATH = os.getenv("WEB_ANALYTICS_PATH", "/web/analytics.html").strip() or "/web/analytics.html"
SESSION_SECRET = os.getenv("SESSION_SECRET") or BOT_TOKEN or ""
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "must_session")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1209600"))
TELEGRAM_AUTH_MAX_AGE_SECONDS = int(os.getenv("TELEGRAM_AUTH_MAX_AGE_SECONDS", "86400"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ONBOARDING_VIDEO_DIR = os.path.join(BASE_DIR, "onboarding")
ONBOARDING_VIDEO_MAP = {
    1: "OnboardingWhatIs.mp4",
    2: "OnboardingCompassWhy.mp4",
    3: "OnboardingWhyQuit.mp4",
    4: "OnboardingHowItWorks.mp4",
    5: "OnboardingPersonalDataset.mp4",
    6: "OnboardingAICoach.mp4",
}
WEB_DIR = Path(BASE_DIR) / "web"
DB_FILE = Path("bot.db")
TELEGRAM_LOGIN_FIELDS = {
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
}

OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

OAUTH_BOT: Optional[Bot] = None
BOT_USERNAME: Optional[str] = None
GOOGLE_AUTH_ALERTED: set[int] = set()

DEFAULT_WEEKLY_REVIEW_TIME = "10:00"
DEFAULT_COACH_PROMPT = (
    "ROLE: “Professor-Coach” — рациональный AI-коуч для анализа дневника\n\n"
    "IDENTITY / PERSONA\n"
    "- Психологический портрет: опытный профессор/наставник 50–60 лет (гендер нейтрален), "
    "спокойный, уверенный, доброжелательный, но без сюсюканья.\n"
    "- Тон: трезвый реалист, слегка скептичный, ориентирован на факты и последствия. "
    "Не комплиментарный “по умолчанию”.\n"
    "- Цель: помочь пользователю стать сильнее и лучше — через ясность, дисциплину, "
    "осознанность, честную обратную связь и практичные шаги.\n\n"
    "NON-NEGOTIABLES (важные правила)\n"
    "1) Не льсти. Не используй пустые похвалы. Хвали только за конкретные действия и результаты.\n"
    "2) Не потакай “слабостям момента”. Помогай выбирать долгосрочную пользу, а не мгновенный комфорт.\n"
    "3) Будь уважительным, но прямым. Говори честно, но без жестокости.\n"
    "4) Всегда отделяй факты (из дневника) от интерпретаций и гипотез.\n"
    "5) Не ставь диагнозов и не делай клинических утверждений. Ты не врач.\n"
    "6) Если есть признаки риска самоповреждения/насилия/острой психической кризисной ситуации — "
    "мягко останови коучинг и предложи обратиться за срочной помощью/к специалисту.\n\n"
    "INPUTS (что тебе приходит)\n"
    "- Пользователь присылает дневник за период (обычно неделя) + иногда цели/контекст.\n"
    "- Формат дневника может быть хаотичным: заметки, эмоции, планы, мысли, события, трекеры.\n\n"
    "CORE TASK\n"
    "Проанализируй дневник и выдай “отчет профессора-коуча”:\n"
    "- заметить паттерны поведения, триггеры, привычки, самосаботаж, сильные стороны (если они подтверждены),\n"
    "- выявить несоответствия между целями и действиями,\n"
    "- предложить реалистичный план корректировок на следующую неделю,\n"
    "- помочь вести диалог: отвечать на вопросы пользователя и уточнять недостающий контекст.\n\n"
    "OUTPUT FORMAT (строго придерживаться)\n"
    "1) TL;DR (3–6 строк)\n"
    "- Самое важное: 1–2 главных паттерна + 1 ключевой рычаг изменения.\n\n"
    "2) FACTS I’M USING\n"
    "- 5–15 коротких буллетов с цитатами/пересказом конкретных моментов из дневника.\n"
    "- Без оценок. Просто что произошло/что сказал пользователь/что сделал.\n\n"
    "3) PATTERNS & MEANING (гипотезы)\n"
    "- 3–7 паттернов.\n"
    "- Для каждого:\n"
    "  - Что я заметил (pattern)\n"
    "  - Чем это может быть обусловлено (hypothesis)\n"
    "  - Насколько я уверен (High/Medium/Low)\n"
    "  - Что нужно уточнить (1 вопрос)\n\n"
    "4) GOALS ALIGNMENT CHECK\n"
    "- Таблица/список:\n"
    "  - Заявленные цели (если есть)\n"
    "  - Действия недели, которые приближали\n"
    "  - Действия недели, которые отдаляли\n"
    "  - “Главная несостыковка недели” (одна фраза, честно)\n\n"
    "5) REALISTIC COACHING (прямая обратная связь)\n"
    "- 5–10 пунктов “вот где ты себя обманываешь / где теряешь энергию / где можно быть жестче к себе”.\n"
    "- Без морализаторства, но с ясными причинами (почему это важно).\n\n"
    "6) NEXT WEEK PLAN (минимально жизнеспособный)\n"
    "- 1 главный фокус недели (ONE THING)\n"
    "- 3 поведенческих правила (простые, измеримые)\n"
    "- 2–4 привычки/ритуала (<=15 минут каждый)\n"
    "- 1 “тяжелый разговор с собой” (что признать/какое решение принять)\n"
    "- 1 эксперимент (A/B тест поведения)\n"
    "- Метрики (2–5 цифр, которые реально собрать)\n\n"
    "8) QUESTIONS FOR YOU (чтобы уточнить)\n"
    "- 3–7 вопросов, максимально конкретных, без “расскажи о себе”.\n"
    "- Если пользователь не отвечает — делай лучшие предположения и отмечай их.\n\n"
    "CONVERSATION MODE (когда пользователь дальше общается)\n"
    "- Отвечай кратко, по делу, задавай 1–2 уточняющих вопроса максимум.\n"
    "- Если пользователь просит “пожалеешь меня/поддержи” — поддержи, но обязательно добавь рациональный шаг: "
    "“что делаем дальше”.\n"
    "- Если пользователь просит план — сначала выяви ограничение (время/энергия/обязательства), потом давай план.\n\n"
    "STYLE GUIDELINES (как звучать)\n"
    "- Голос: “профессор-наставник”: спокойный, уверенный, без пафоса.\n"
    "- Лексика: понятная, без эзотерики. Иногда допускается мягкая ирония.\n"
    "- Не делай “бесконечных” списков. Лучше меньше, но применимо.\n"
    "- Не пытайся быть другом. Ты — наставник, который уважает пользователя и его потенциал.\n\n"
    "DEFAULT ASSUMPTIONS (если не хватает данных)\n"
    "- Предпочитай маленькие устойчивые изменения вместо грандиозных рывков.\n"
    "- Сначала сон/энергия/режим → потом продуктивность.\n"
    "- Поведение важнее мотивации: строим систему, а не надеемся на настроение.\n\n"
    "FIRST MESSAGE BEHAVIOR\n"
    "Когда впервые получаешь дневник:\n"
    "- Сразу дай отчет по структуре выше.\n"
    "- В конце спроси: “Какая 1 цель на следующую неделю самая важная?”"
)
DEFAULT_JOURNAL_PROMPT = (
    "Расскажи про свой день:\n"
    "1) Что сегодня было?\n"
    "2) Что важного случилось?\n"
    "3) Что вышло хорошо?\n"
    "4) Что вышло плохо?\n"
    "5) Как это можно улучшить?\n\n"
    "Можно голосом или текстом. Можно несколькими сообщениями."
)
WEEKLY_REPORT_INSTRUCTIONS = (
    "Сделай недельный отчет по дневнику. Опиши темы/паттерны, что помогает, что мешает, "
    "и 2-3 эксперимента на следующую неделю. Будь конкретным и дружелюбным. "
    "Не выдумывай фактов."
)
JOURNAL_PAGE_SIZE = 7
REPORT_PAGE_SIZE = 5
EVENING_DIARY_TRIGGER_WINDOW = dt.timedelta(hours=4)
JOURNAL_ACK_DEBOUNCE_SEC = 1.5


# ----------------------------
# Database helpers
# ----------------------------
def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_user_columns()
    ensure_tracker_columns()
    normalize_tracker_booleans()
    ensure_journal_columns()


def ensure_user_columns() -> None:
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("users")}
    statements = []
    if "morning_time" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN morning_time VARCHAR(5)")
    if "evening_time" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN evening_time VARCHAR(5)")
    if "morning_last_date" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN morning_last_date DATE")
    if "evening_last_date" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN evening_last_date DATE")
    if "streak_last_date" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN streak_last_date DATE")
    if "first_name" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN first_name VARCHAR(128)")
    if "last_name" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN last_name VARCHAR(128)")
    if "username" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN username VARCHAR(128)")
    if "google_email" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_email VARCHAR(255)")
    if "google_sheet_id" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_sheet_id VARCHAR(128)")
    if "google_sheet_url" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_sheet_url VARCHAR(512)")
    if "google_connected_at" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_connected_at TIMESTAMPTZ")
    if "google_access_token" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_access_token TEXT")
    if "google_refresh_token" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_refresh_token TEXT")
    if "google_token_expiry" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_token_expiry TIMESTAMPTZ")
    if "google_oauth_state" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_oauth_state VARCHAR(128)")
    if "google_oauth_state_expires_at" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN google_oauth_state_expires_at TIMESTAMPTZ")
    if "weekly_review_time" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN weekly_review_time VARCHAR(5)")
    if "weekly_review_last_date" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN weekly_review_last_date DATE")
    if "coach_prompt" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN coach_prompt TEXT")
    if "onboarding_done" not in existing:
        statements.append("ALTER TABLE users ADD COLUMN onboarding_done BOOLEAN DEFAULT FALSE")
    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))


def ensure_tracker_columns() -> None:
    inspector = inspect(engine)
    if "trackers" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("trackers")}
    statements = []
    if "streak_enabled" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN streak_enabled BOOLEAN DEFAULT TRUE")
    if "streak_mode" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN streak_mode VARCHAR(16) DEFAULT 'activity'")
    if "streak_period" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN streak_period VARCHAR(16) DEFAULT 'day'")
    if "streak_min_value" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN streak_min_value FLOAT DEFAULT 0")
    if "streak_partial_ok" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN streak_partial_ok BOOLEAN DEFAULT TRUE")
    if "xp_count_map" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN xp_count_map TEXT")
    if "xp_scale_min" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN xp_scale_min INTEGER")
    if "xp_scale_max" not in existing:
        statements.append("ALTER TABLE trackers ADD COLUMN xp_scale_max INTEGER")
    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))


def normalize_tracker_booleans() -> None:
    inspector = inspect(engine)
    if "trackers" not in inspector.get_table_names():
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE trackers SET active=1 "
                "WHERE active IN ('true','True','TRUE')"
            )
        )
        conn.execute(
            text(
                "UPDATE trackers SET active=0 "
                "WHERE active IN ('false','False','FALSE')"
            )
        )
        conn.execute(
            text(
                "UPDATE trackers SET streak_enabled=1 "
                "WHERE streak_enabled IN ('true','True','TRUE')"
            )
        )
        conn.execute(
            text(
                "UPDATE trackers SET streak_enabled=0 "
                "WHERE streak_enabled IN ('false','False','FALSE')"
            )
        )
        conn.execute(
            text(
                "UPDATE trackers SET streak_partial_ok=1 "
                "WHERE streak_partial_ok IN ('true','True','TRUE')"
            )
        )
        conn.execute(
            text(
                "UPDATE trackers SET streak_partial_ok=0 "
                "WHERE streak_partial_ok IN ('false','False','FALSE')"
            )
        )


def ensure_journal_columns() -> None:
    inspector = inspect(engine)
    if "journal_entries" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("journal_entries")}
    statements = []
    if "status" not in existing:
        statements.append(
            "ALTER TABLE journal_entries ADD COLUMN status VARCHAR(16) DEFAULT 'closed'"
        )
    if "created_at" not in existing:
        statements.append(
            "ALTER TABLE journal_entries ADD COLUMN created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
        )
    if "updated_at" not in existing:
        statements.append(
            "ALTER TABLE journal_entries ADD COLUMN updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
        )
    if "last_message_at" not in existing:
        statements.append(
            "ALTER TABLE journal_entries ADD COLUMN last_message_at TIMESTAMPTZ"
        )
    if "closed_at" not in existing:
        statements.append("ALTER TABLE journal_entries ADD COLUMN closed_at TIMESTAMPTZ")
    if "auto_closed" not in existing:
        statements.append(
            "ALTER TABLE journal_entries ADD COLUMN auto_closed BOOLEAN DEFAULT FALSE"
        )
    if statements:
        with engine.begin() as conn:
            for stmt in statements:
                conn.execute(text(stmt))


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


def _format_tz(offset_minutes: int) -> str:
    sign = "+" if offset_minutes >= 0 else "-"
    total = abs(offset_minutes)
    hours, minutes = divmod(total, 60)
    if minutes:
        return f"UTC{sign}{hours}:{minutes:02d}"
    return f"UTC{sign}{hours}"


def _infer_tz_from_local_time(local_time: str) -> str:
    now_utc = _utcnow()
    utc_minutes = now_utc.hour * 60 + now_utc.minute
    local_minutes = int(local_time[:2]) * 60 + int(local_time[3:])
    diff = local_minutes - utc_minutes
    if diff > 720:
        diff -= 1440
    if diff < -720:
        diff += 1440
    return _format_tz(diff)


def today_iso(tz: str = "UTC") -> dt.date:
    offset = dt.timedelta(minutes=_tz_offset_minutes(tz))
    return (_utcnow() + offset).date()


def parse_date_input(value: str, tz: str) -> Optional[dt.date]:
    text = value.strip().lower()
    if text in {"сегодня", "today"}:
        return today_iso(tz)
    if text in {"вчера", "yesterday"}:
        return today_iso(tz) - dt.timedelta(days=1)
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        pass
    match = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", text)
    if not match:
        return None
    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = today_iso(tz).year
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


def parse_time_input(value: str) -> Optional[str]:
    text = value.strip().lower()
    if text in {"нет", "no", "off", "stop", "выкл", "откл"}:
        return ""
    match = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def build_oauth_url(state: str) -> str:
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_REDIRECT_URI:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_REDIRECT_URI is not set")
    params = {
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_oauth_code(code: str) -> dict:
    if not GOOGLE_OAUTH_CLIENT_ID or not GOOGLE_OAUTH_CLIENT_SECRET or not GOOGLE_OAUTH_REDIRECT_URI:
        raise RuntimeError(
            "GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET/GOOGLE_OAUTH_REDIRECT_URI is not set"
        )
    payload = {
        "code": code,
        "client_id": GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    async with ClientSession() as session:
        async with session.post("https://oauth2.googleapis.com/token", data=payload) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"OAuth token error: {data}")
            return data


def build_user_credentials(
    access_token: str, refresh_token: Optional[str], expiry: Optional[dt.datetime]
) -> Credentials:
    expiry_naive = None
    if expiry:
        expiry_naive = expiry.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=OAUTH_SCOPES,
        expiry=expiry_naive,
    )


def parse_count_xp_map(raw: str) -> dict[int, int]:
    normalized = raw.strip()
    for ch in ("–", "—", "−"):
        normalized = normalized.replace(ch, "-")
    tokens = re.split(r"[\s,;]+", normalized)
    result: dict[int, int] = {}
    for token in tokens:
        if not token:
            continue
        match = re.match(r"^(\d+)\s*[-:=]\s*(\d+)$", token)
        if not match:
            raise ValueError("bad_token")
        count = int(match.group(1))
        xp = int(match.group(2))
        if count <= 0:
            raise ValueError("count")
        result[count] = xp
    if not result:
        raise ValueError("empty")
    return result


def format_count_xp_map(mapping: dict[int, int]) -> str:
    return " ".join(f"{k}-{v}" for k, v in sorted(mapping.items()))


def load_count_xp_map(tracker: Tracker) -> dict[int, int]:
    if not tracker.xp_count_map:
        return {}
    try:
        data = json.loads(tracker.xp_count_map)
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


def count_value_buttons(tracker: Tracker) -> list[list[InlineKeyboardButton]]:
    mapping = load_count_xp_map(tracker)
    values = sorted(mapping.keys()) if mapping else [1, 5, 10]
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for value in values:
        row.append(
            InlineKeyboardButton(
                text=str(value),
                callback_data=f"tracker:add:{tracker.id}:{value}",
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def tracker_xp_for_value(tracker: Tracker, value: float, partial: bool = False) -> int:
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
        mapping = load_count_xp_map(tracker)
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


_google_sync_tasks: dict[int, asyncio.Task] = {}


def _prepare_google_oauth_url(user_id: int) -> str:
    state_token = secrets.token_urlsafe(24)
    expires_at = _utcnow() + dt.timedelta(minutes=10)
    update_user_google_oauth_state(user_id, state_token, expires_at)
    return build_oauth_url(state_token)


def _google_oauth_kb(
    auth_url: str,
    label: str = "🔗 Подключить Google",
    extra_rows: Optional[list[list[InlineKeyboardButton]]] = None,
) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=label, url=auth_url)]]
    if extra_rows:
        rows.extend(extra_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _notify_google_auth_expired(user_id: int, tg_id: int) -> None:
    if user_id in GOOGLE_AUTH_ALERTED:
        return
    GOOGLE_AUTH_ALERTED.add(user_id)
    clear_user_google_oauth(user_id, reset_alert=False)
    if not OAUTH_BOT:
        return
    try:
        auth_url = _prepare_google_oauth_url(user_id)
        kb = _google_oauth_kb(auth_url, label="🔄 Переподключить Google")
        text = (
            "⚠️ Истек доступ к Google Sheets. Старую таблицу отвязал.\n"
            "Нажми, чтобы переподключить — после этого синхронизация пойдет автоматически."
        )
        await OAUTH_BOT.send_message(tg_id, text, reply_markup=kb)
    except RuntimeError as exc:
        await OAUTH_BOT.send_message(
            tg_id,
            "⚠️ Истек доступ к Google Sheets.\n"
            f"Не могу выдать ссылку: {exc}\n"
            "Открой Настройки → Google Sheets и попробуй снова.",
        )


def request_google_sync(user_id: int, delay: float = 2.0) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    existing = _google_sync_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()
    _google_sync_tasks[user_id] = loop.create_task(_google_sync_worker(user_id, delay))


async def _google_sync_worker(user_id: int, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        await _sync_user_to_google(user_id)
    except asyncio.CancelledError:
        return
    except Exception:
        traceback.print_exc()
    finally:
        task = _google_sync_tasks.get(user_id)
        if task and task.done():
            _google_sync_tasks.pop(user_id, None)


async def _sync_user_to_google(user_id: int) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user or not user.google_sheet_id or not user.google_access_token:
            return
        tg_id = user.tg_id
        creds = build_user_credentials(
            user.google_access_token,
            user.google_refresh_token,
            user.google_token_expiry,
        )
        sheet_id = user.google_sheet_id

    if creds.expired:
        if user_id in GOOGLE_AUTH_ALERTED:
            return
        if not creds.refresh_token:
            await _notify_google_auth_expired(user_id, tg_id)
            return
        try:
            await asyncio.to_thread(creds.refresh, Request())
        except RefreshError:
            await _notify_google_auth_expired(user_id, tg_id)
            return
        update_user_google_tokens(
            user_id,
            creds.token,
            creds.refresh_token,
            _ensure_utc(creds.expiry),
        )

    try:
        from google_sheets import push_raw_data_with_credentials, sync_habits_grid_with_credentials
    except Exception:
        traceback.print_exc()
        return

    await asyncio.to_thread(push_raw_data_with_credentials, sheet_id, user_id, creds)
    await asyncio.to_thread(
        sync_habits_grid_with_credentials, sheet_id, user_id, creds, delete_setup=False
    )


async def oauth_callback(request: web.Request) -> web.Response:
    params = request.rel_url.query
    error = params.get("error")
    if error:
        return web.Response(text=f"OAuth error: {error}", status=400)

    state = params.get("state")
    code = params.get("code")
    if not state or not code:
        return web.Response(text="Missing state or code", status=400)

    user = get_user_by_oauth_state(state)
    if not user:
        return web.Response(text="Invalid state", status=400)

    state_expires_at = _ensure_utc(user.google_oauth_state_expires_at)
    if state_expires_at and state_expires_at < _utcnow():
        return web.Response(text="State expired, try again", status=400)

    try:
        token_data = await exchange_oauth_code(code)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        if not access_token:
            raise RuntimeError("access_token missing from response")
        expiry = _utcnow() + dt.timedelta(seconds=int(expires_in)) if expires_in else None
        update_user_google_tokens(user.id, access_token, refresh_token, expiry)
        creds = build_user_credentials(access_token, refresh_token, expiry)
        try:
            from google_sheets import create_user_sheet_with_credentials
        except Exception as exc:
            raise RuntimeError(f"Google Sheets module error: {exc}") from exc

        sheet_id, url = await asyncio.to_thread(
            create_user_sheet_with_credentials, user.id, user.tg_id, creds
        )
        update_user_google_sheet(user.id, sheet_id, url, email=None)
        clear_user_google_oauth_state(user.id)
        request_google_sync(user.id, delay=0)
        if OAUTH_BOT:
            if not user.onboarding_done:
                await OAUTH_BOT.send_message(
                    user.tg_id,
                    f"Готово! Вот твоя таблица:\n{url}",
                    reply_markup=onboarding_next_kb(14),
                )
            else:
                await OAUTH_BOT.send_message(
                    user.tg_id,
                    f"Готово! Таблица:\n{url}",
                    reply_markup=main_reply_kb(user.tg_id),
                )
                await OAUTH_BOT.send_message(
                    user.tg_id,
                    settings_text(get_or_create_user(user.tg_id)),
                    reply_markup=settings_inline(),
                )
        return web.Response(text="OK. Таблица создана, вернись в Telegram.")
    except Exception as exc:
        traceback.print_exc()
        if OAUTH_BOT:
            await OAUTH_BOT.send_message(
                user.tg_id, f"Ошибка подключения Google Sheets: {html.escape(str(exc))}"
            )
        return web.Response(text="OAuth failed. Check bot for details.", status=500)


def _analytics_path() -> str:
    path = WEB_ANALYTICS_PATH or "/web/analytics.html"
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def _request_base_url(request: web.Request) -> str:
    if WEB_BASE_URL:
        return WEB_BASE_URL
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("X-Forwarded-Host", request.host)
    return f"{proto}://{host}"


def build_webapp_url(tg_id: Optional[int] = None) -> Optional[str]:
    if not WEB_BASE_URL:
        return None
    base = f"{WEB_BASE_URL}{_analytics_path()}"
    if not tg_id:
        return base
    token = build_session_cookie_value(int(tg_id))
    return f"{base}?{urlencode({'token': token})}"


def _session_secret_bytes() -> bytes:
    if not SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET is not set.")
    return SESSION_SECRET.encode()


def build_session_cookie_value(tg_id: int) -> str:
    issued_at = int(time.time())
    payload = f"{tg_id}:{issued_at}"
    signature = hmac.new(_session_secret_bytes(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def parse_session_cookie_value(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    tg_id_s, issued_at_s, signature = parts
    if not tg_id_s.isdigit() or not issued_at_s.isdigit():
        return None
    payload = f"{tg_id_s}:{issued_at_s}"
    expected = hmac.new(_session_secret_bytes(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    if SESSION_TTL_SECONDS:
        if time.time() - int(issued_at_s) > SESSION_TTL_SECONDS:
            return None
    return int(tg_id_s)


def _auth_date_valid(auth_date: Optional[str]) -> bool:
    if not auth_date:
        return True
    try:
        ts = int(auth_date)
    except (TypeError, ValueError):
        return False
    if ts <= 0:
        return False
    return time.time() - ts <= TELEGRAM_AUTH_MAX_AGE_SECONDS


def verify_telegram_login_payload(payload: dict[str, str]) -> Optional[dict[str, str]]:
    if not BOT_TOKEN:
        return None
    raw = {k: v for k, v in payload.items()}
    hash_value = raw.pop("hash", None)
    if not hash_value:
        return None
    data = {k: raw[k] for k in raw if k in TELEGRAM_LOGIN_FIELDS}
    if not _auth_date_valid(data.get("auth_date")):
        return None
    if not data.get("id"):
        return None
    data_check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, hash_value):
        return None
    return data


def verify_telegram_webapp_init_data(init_data: str) -> Optional[dict[str, str]]:
    if not BOT_TOKEN:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    hash_value = parsed.pop("hash", None)
    if not hash_value:
        return None
    if not _auth_date_valid(parsed.get("auth_date")):
        return None
    data_check = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, hash_value):
        return None
    user_json = parsed.get("user")
    if not user_json:
        return None
    try:
        user_payload = json.loads(user_json)
    except json.JSONDecodeError:
        return None
    return {
        "id": str(user_payload.get("id") or ""),
        "first_name": str(user_payload.get("first_name") or ""),
        "last_name": str(user_payload.get("last_name") or ""),
        "username": str(user_payload.get("username") or ""),
    }


def upsert_user_from_auth(payload: dict[str, str]) -> Optional[User]:
    tg_id_raw = payload.get("id")
    if not tg_id_raw or not str(tg_id_raw).isdigit():
        return None
    tg_id = int(tg_id_raw)
    get_or_create_user(tg_id)
    with db_session() as session:
        user = session.query(User).filter(User.tg_id == tg_id).one_or_none()
        if not user:
            return None
        changed = False
        for key in ("first_name", "last_name", "username"):
            value = payload.get(key)
            if value and getattr(user, key) != value:
                setattr(user, key, value)
                changed = True
        if changed:
            session.flush()
        return user


def get_user_snapshot_by_tg_id(tg_id: int) -> Optional[dict]:
    with db_session() as session:
        user = session.query(User).filter(User.tg_id == tg_id).one_or_none()
        if not user:
            return None
        return {
            "id": user.id,
            "tg_id": user.tg_id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "username": user.username,
        }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _delete_by_user(conn: sqlite3.Connection, table: str, user_id: int) -> None:
    if not _table_exists(conn, table):
        return
    conn.execute(f"DELETE FROM {table} WHERE user_id != ?", (user_id,))


def _prune_user_db(conn: sqlite3.Connection, user_id: int) -> None:
    if _table_exists(conn, "users"):
        conn.execute("DELETE FROM users WHERE id != ?", (user_id,))
        conn.execute(
            "UPDATE users SET google_access_token = NULL, google_refresh_token = NULL, "
            "google_token_expiry = NULL, google_oauth_state = NULL, "
            "google_oauth_state_expires_at = NULL WHERE id = ?",
            (user_id,),
        )

    tracker_ids = []
    if _table_exists(conn, "trackers"):
        rows = conn.execute("SELECT id FROM trackers WHERE user_id = ?", (user_id,)).fetchall()
        tracker_ids = [row[0] for row in rows]
        if tracker_ids:
            placeholders = ",".join("?" for _ in tracker_ids)
            conn.execute(
                f"DELETE FROM trackers WHERE id NOT IN ({placeholders})",
                tracker_ids,
            )
        else:
            conn.execute("DELETE FROM trackers")
    if tracker_ids:
        placeholders = ",".join("?" for _ in tracker_ids)
        for table in ("tracker_logs", "tracker_goals", "tracker_goal_display"):
            if _table_exists(conn, table):
                conn.execute(
                    f"DELETE FROM {table} WHERE tracker_id NOT IN ({placeholders})",
                    tracker_ids,
                )
    else:
        for table in ("tracker_logs", "tracker_goals", "tracker_goal_display"):
            if _table_exists(conn, table):
                conn.execute(f"DELETE FROM {table}")

    for table in (
        "missions",
        "journal_entries",
        "journal_messages",
        "journal_weekly_reports",
        "coach_messages",
    ):
        _delete_by_user(conn, table, user_id)


def build_user_db_bytes(user_id: int) -> bytes:
    if not DB_FILE.exists():
        raise FileNotFoundError("bot.db not found")
    with sqlite3.connect(DB_FILE) as source:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
            temp_path = temp_file.name
        try:
            with sqlite3.connect(temp_path) as target:
                source.backup(target)
                _prune_user_db(target, user_id)
                target.commit()
            return Path(temp_path).read_bytes()
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


async def analytics_page(request: web.Request) -> web.StreamResponse:
    path = WEB_DIR / "analytics.html"
    if not path.exists():
        return web.Response(text="Analytics page not found.", status=404)
    response = web.FileResponse(path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    token = request.query.get("token")
    if token:
        tg_id = parse_session_cookie_value(token)
        if tg_id and get_user_snapshot_by_tg_id(tg_id):
            secure_cookie = (
                request.headers.get("X-Forwarded-Proto", request.scheme) == "https"
                or WEB_BASE_URL.startswith("https://")
            )
            response.set_cookie(
                SESSION_COOKIE_NAME,
                build_session_cookie_value(tg_id),
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                samesite="Lax",
                secure=secure_cookie,
            )
    return response


async def auth_config(request: web.Request) -> web.Response:
    base_url = _request_base_url(request)
    return_to = _analytics_path()
    auth_url = f"{base_url}/auth/telegram?return_to={return_to}"
    return web.json_response(
        {
            "bot_username": BOT_USERNAME,
            "auth_url": auth_url,
            "webapp_url": build_webapp_url(),
        }
    )


async def auth_me(request: web.Request) -> web.Response:
    tg_id = parse_session_cookie_value(request.cookies.get(SESSION_COOKIE_NAME))
    if not tg_id:
        return web.json_response({"ok": False}, status=401)
    snapshot = get_user_snapshot_by_tg_id(tg_id)
    if not snapshot:
        return web.json_response({"ok": False}, status=401)
    return web.json_response({"ok": True, "user": snapshot})


async def auth_logout(request: web.Request) -> web.Response:
    response = web.json_response({"ok": True})
    response.del_cookie(SESSION_COOKIE_NAME)
    return response


async def auth_telegram(request: web.Request) -> web.StreamResponse:
    user_payload: Optional[dict[str, str]] = None
    token: Optional[str] = None
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = {}
        token = body.get("token") if isinstance(body, dict) else None
        init_data = body.get("init_data") or body.get("initData")
        if init_data:
            user_payload = verify_telegram_webapp_init_data(str(init_data))
        elif body:
            user_payload = verify_telegram_login_payload({k: str(v) for k, v in body.items()})
    else:
        token = request.query.get("token")
        user_payload = verify_telegram_login_payload({k: str(v) for k, v in request.query.items()})

    if token and not user_payload:
        tg_id = parse_session_cookie_value(str(token))
        if tg_id:
            get_or_create_user(tg_id)
            user_payload = {"id": str(tg_id)}

    if not user_payload:
        return web.json_response({"ok": False, "error": "invalid_auth"}, status=401)

    user = upsert_user_from_auth(user_payload)
    if not user:
        return web.json_response({"ok": False, "error": "user_not_found"}, status=401)

    cookie_value = build_session_cookie_value(user.tg_id)
    secure_cookie = (
        request.headers.get("X-Forwarded-Proto", request.scheme) == "https"
        or WEB_BASE_URL.startswith("https://")
    )
    if request.method == "GET":
        return_to = request.query.get("return_to") or _analytics_path()
        if not return_to.startswith("/") or "://" in return_to:
            return_to = _analytics_path()
        response = web.HTTPFound(location=return_to)
    else:
        response = web.json_response({"ok": True})
    response.set_cookie(
        SESSION_COOKIE_NAME,
        cookie_value,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="Lax",
        secure=secure_cookie,
    )
    return response


async def api_db(request: web.Request) -> web.Response:
    tg_id = parse_session_cookie_value(request.cookies.get(SESSION_COOKIE_NAME))
    if not tg_id:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    snapshot = get_user_snapshot_by_tg_id(tg_id)
    if not snapshot:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    try:
        payload = build_user_db_bytes(snapshot["id"])
    except Exception:
        traceback.print_exc()
        return web.json_response({"ok": False, "error": "export_failed"}, status=500)
    headers = {
        "Content-Disposition": "attachment; filename=bot.db",
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return web.Response(body=payload, headers=headers, content_type="application/octet-stream")


async def start_web_server(bot: Bot) -> None:
    global OAUTH_BOT
    OAUTH_BOT = bot
    app = web.Application()
    app.router.add_get("/oauth2/google/callback", oauth_callback)
    app.router.add_get("/", analytics_page)
    app.router.add_get("/web/analytics.html", analytics_page)
    app.router.add_get("/auth/config", auth_config)
    app.router.add_get("/auth/me", auth_me)
    app.router.add_post("/auth/logout", auth_logout)
    app.router.add_get("/auth/telegram", auth_telegram)
    app.router.add_post("/auth/telegram", auth_telegram)
    app.router.add_get("/api/db", api_db)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", GOOGLE_OAUTH_PORT)
    await site.start()


def xp_needed(level: int) -> int:
    """
    XP needed to go from `level` to `level+1`.
    Formula: 100 + 15*(lvl-1) + (lvl-1)**1.35 * 5 (clamped to int).
    """
    if level < 1:
        level = 1
    return int(100 + 15 * (level - 1) + ((level - 1) ** 1.35) * 5)


def add_xp(user_id: int, amount: int) -> Tuple[int, int, bool]:
    """
    Add XP to user.
    Returns (new_level, xp_in_level, level_up_happened)
    """
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise RuntimeError("User not found for XP update.")
        if amount <= 0:
            return user.level, user.xp, False

        lvl = user.level
        xp = user.xp + amount
        level_up = False
        while xp >= xp_needed(lvl):
            xp -= xp_needed(lvl)
            lvl += 1
            level_up = True
        user.level = lvl
        user.xp = xp
        return lvl, xp, level_up


def _normalize_user_identity(tg_user: TgUser) -> tuple[Optional[str], Optional[str], Optional[str]]:
    first = (tg_user.first_name or "").strip() or None
    last = (tg_user.last_name or "").strip() or None
    username = (tg_user.username or "").strip() or None
    return first, last, username


def _update_user_identity(user: User, tg_user: TgUser) -> bool:
    first, last, username = _normalize_user_identity(tg_user)
    changed = False
    if user.first_name != first:
        user.first_name = first
        changed = True
    if user.last_name != last:
        user.last_name = last
        changed = True
    if user.username != username:
        user.username = username
        changed = True
    return changed


def _update_user_streak_on_activity(user: User) -> bool:
    today = today_iso(user.tz)
    last_date = user.streak_last_date
    if last_date == today:
        return False
    if last_date == today - dt.timedelta(days=1):
        user.streak = (user.streak or 0) + 1
    else:
        user.streak = 1
    user.streak_last_date = today
    return True


def get_or_create_user(
    tg_id: int,
    *,
    touch_streak: bool = False,
    tg_user: Optional[TgUser] = None,
) -> User:
    with db_session() as session:
        user = session.query(User).filter(User.tg_id == tg_id).one_or_none()
        if user:
            changed = False
            if not user.weekly_review_time:
                user.weekly_review_time = DEFAULT_WEEKLY_REVIEW_TIME
                changed = True
            if user.coach_prompt is None:
                user.coach_prompt = DEFAULT_COACH_PROMPT
                changed = True
            if user.onboarding_done is None:
                user.onboarding_done = False
                changed = True
            if tg_user and _update_user_identity(user, tg_user):
                changed = True
            if touch_streak and _update_user_streak_on_activity(user):
                changed = True
            if changed:
                session.flush()
            return user
        first, last, username = _normalize_user_identity(tg_user) if tg_user else (None, None, None)
        user = User(
            tg_id=tg_id,
            first_name=first,
            last_name=last,
            username=username,
            tz="UTC",
            level=1,
            xp=0,
            streak=0,
            weekly_review_time=DEFAULT_WEEKLY_REVIEW_TIME,
            coach_prompt=DEFAULT_COACH_PROMPT,
            onboarding_done=False,
        )
        if touch_streak:
            _update_user_streak_on_activity(user)
        session.add(user)
        session.flush()
        return user


def update_user_reminders(
    user_id: int, morning_time: Optional[str] = None, evening_time: Optional[str] = None
) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        if morning_time is not None:
            user.morning_time = morning_time or None
            if not morning_time:
                user.morning_last_date = None
        if evening_time is not None:
            user.evening_time = evening_time or None
            if not evening_time:
                user.evening_last_date = None


def update_user_weekly_review_time(user_id: int, time_str: Optional[str]) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.weekly_review_time = time_str or None
        if not time_str:
            user.weekly_review_last_date = None


def update_user_coach_prompt(user_id: int, prompt: str) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.coach_prompt = prompt


def update_user_timezone(user_id: int, tz: str) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.tz = tz
    request_google_sync(user_id)


def update_user_google_sheet(
    user_id: int,
    sheet_id: Optional[str],
    sheet_url: Optional[str],
    email: Optional[str] = None,
) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        if email is not None:
            user.google_email = email
        user.google_sheet_id = sheet_id or None
        user.google_sheet_url = sheet_url or None
        user.google_connected_at = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc) if sheet_id else None


def update_user_google_tokens(
    user_id: int,
    access_token: str,
    refresh_token: Optional[str],
    expiry: Optional[dt.datetime],
) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.google_access_token = access_token
        if refresh_token:
            user.google_refresh_token = refresh_token
        user.google_token_expiry = expiry
    GOOGLE_AUTH_ALERTED.discard(user_id)


def set_onboarding_done(user_id: int, done: bool = True) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.onboarding_done = done

def update_user_google_oauth_state(user_id: int, state: str, expires_at: dt.datetime) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.google_oauth_state = state
        user.google_oauth_state_expires_at = expires_at


def clear_user_google_oauth(user_id: int, reset_alert: bool = True) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.google_access_token = None
        user.google_refresh_token = None
        user.google_token_expiry = None
        user.google_oauth_state = None
        user.google_oauth_state_expires_at = None
        user.google_sheet_id = None
        user.google_sheet_url = None
        user.google_connected_at = None
    if reset_alert:
        GOOGLE_AUTH_ALERTED.discard(user_id)


def clear_user_google_oauth_state(user_id: int) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.google_oauth_state = None
        user.google_oauth_state_expires_at = None


def get_user_by_oauth_state(state: str) -> Optional[User]:
    with db_session() as session:
        return session.query(User).filter(User.google_oauth_state == state).one_or_none()


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _ensure_utc(value: Optional[dt.datetime]) -> Optional[dt.datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def _select_chat_provider() -> str:
    if AI_PROVIDER in {"openai", "deepseek"}:
        return AI_PROVIDER
    if OPENAI_API_KEY:
        return "openai"
    if DEEPSEEK_API_KEY:
        return "deepseek"
    return "openai"


async def llm_chat(
    messages: list[dict],
    temperature: float = 0.6,
    max_tokens: Optional[int] = 800,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[str, str]:
    selected = provider or _select_chat_provider()
    if selected == "deepseek":
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")
        url = f"{DEEPSEEK_API_BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        model_name = model or DEEPSEEK_CHAT_MODEL
    else:
        if not OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set")
        url = f"{OPENAI_API_BASE}/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        model_name = model or OPENAI_CHAT_MODEL

    payload: dict = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    async with ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=60) as resp:
            data = await resp.json()
            if resp.status != 200:
                raise RuntimeError(f"LLM error: {data}")
            content = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            return content, model_name


async def transcribe_voice_message(message: Message) -> Optional[str]:
    if not OPENAI_API_KEY or not message.voice:
        return None
    try:
        file = await message.bot.get_file(message.voice.file_id)
        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        form = FormData()
        form.add_field("model", OPENAI_AUDIO_MODEL)
        form.add_field(
            "file",
            buf,
            filename="voice.ogg",
            content_type="audio/ogg",
        )
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
        async with ClientSession() as session:
            async with session.post(
                f"{OPENAI_API_BASE}/audio/transcriptions",
                headers=headers,
                data=form,
                timeout=60,
            ) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"Transcription error {resp.status}: {raw}")
                data = json.loads(raw)
                text = (data.get("text") or "").strip()
                return text or None
    except Exception:
        traceback.print_exc()
        return None


def _build_tracker_context(user: User, reference_date: dt.date) -> str:
    trackers = list_trackers(user.id)
    if not trackers:
        return "Трекеров нет."
    lines = []
    for tracker in trackers:
        unit = tracker.unit or ""
        streak = tracker_streak_value(tracker, reference_date)
        goals = get_tracker_goals(tracker.id)
        week_goal = goals.get("week")
        month_goal = goals.get("month")
        year_goal = goals.get("year")
        week_progress = tracker_progress_period(tracker.id, "week", reference_date)
        month_progress = tracker_progress_period(tracker.id, "month", reference_date)
        year_progress = tracker_progress_period(tracker.id, "year", reference_date)
        parts = [
            f"{tracker.name} ({tracker.type})",
            f"стрик {streak}",
            f"неделя {format_value(week_progress)}{unit}",
            f"месяц {format_value(month_progress)}{unit}",
            f"год {format_value(year_progress)}{unit}",
        ]
        if week_goal:
            parts.append(f"цель неделя {format_value(week_goal)}{unit}")
        if month_goal:
            parts.append(f"цель месяц {format_value(month_goal)}{unit}")
        if year_goal:
            parts.append(f"цель год {format_value(year_goal)}{unit}")
        lines.append("- " + " | ".join(parts))
    return "\n".join(lines)


def _build_journal_notes(entries: list[JournalEntry]) -> str:
    lines = []
    for entry in entries:
        text = (entry.text or "").strip()
        if not text:
            continue
        date_label = entry.date.strftime("%d.%m.%Y")
        lines.append(f"{date_label}: {text}")
    if not lines:
        return "Нет заметок."
    return "\n".join(lines)


def _build_coach_history(user_id: int) -> str:
    messages = list_coach_messages(user_id)
    if not messages:
        return "Нет истории чата."
    report_ids = {m.report_id for m in messages if m.report_id}
    report_map: dict[int, str] = {}
    if report_ids:
        with db_session() as session:
            rows = (
                session.query(JournalWeeklyReport)
                .filter(JournalWeeklyReport.id.in_(report_ids))
                .all()
            )
        for row in rows:
            start = row.week_start.strftime("%d.%m.%Y")
            end = row.week_end.strftime("%d.%m.%Y")
            report_map[row.id] = f"{start}–{end}"
    lines = []
    for msg in messages:
        week_label = report_map.get(msg.report_id, "без недели")
        lines.append(f"[Неделя {week_label}] {msg.role}: {msg.content}")
    return "\n".join(lines)


def build_weekly_report_messages(
    user: User, week_start: dt.date, week_end: dt.date
) -> tuple[list[dict], str]:
    entries = list_journal_entries_range(user.id, week_start, week_end)
    notes_text = _build_journal_notes(entries)
    tracker_context = _build_tracker_context(user, week_end)
    context = (
        "Контекст пользователя:\n"
        f"Часовой пояс: {user.tz}\n"
        f"Уровень: {user.level}, XP: {user.xp}, общий стрик: {user.streak}\n\n"
        "Привычки и прогресс:\n"
        f"{tracker_context}\n\n"
        "Заметки за неделю:\n"
        f"{notes_text}\n"
    )
    system_prompt = (user.coach_prompt or DEFAULT_COACH_PROMPT) + "\n\n" + WEEKLY_REPORT_INSTRUCTIONS
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": context},
    ]
    return messages, notes_text


def build_coach_messages(user: User, user_input: str) -> list[dict]:
    today = today_iso(user.tz)
    tracker_context = _build_tracker_context(user, today)
    notes_text = _build_journal_notes(list_all_journal_entries(user.id))
    history_text = _build_coach_history(user.id)
    context = (
        "Контекст пользователя:\n"
        f"Часовой пояс: {user.tz}\n"
        f"Уровень: {user.level}, XP: {user.xp}, общий стрик: {user.streak}\n\n"
        "Привычки и прогресс:\n"
        f"{tracker_context}\n\n"
        "Заметки (по датам):\n"
        f"{notes_text}\n\n"
        "История чата (по неделям):\n"
        f"{history_text}\n"
    )
    prompt = user.coach_prompt or DEFAULT_COACH_PROMPT
    return [
        {"role": "system", "content": prompt},
        {"role": "system", "content": context},
        {"role": "user", "content": user_input},
    ]


def weekly_report_inline(report_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Обсудить неделю", callback_data=f"coach:start:{report_id}")],
            [InlineKeyboardButton(text="📚 Дневник", callback_data="journal:menu")],
        ]
    )


async def generate_weekly_report(
    user: User, week_start: dt.date, week_end: dt.date
) -> Optional[JournalWeeklyReport]:
    existing = get_weekly_report(user.id, week_start)
    if existing:
        return existing
    messages, notes_text = build_weekly_report_messages(user, week_start, week_end)
    if notes_text == "Нет заметок.":
        return None
    report_text, model_name = await llm_chat(messages, temperature=0.5, max_tokens=900)
    return save_weekly_report(user.id, week_start, week_end, report_text, model_name)


def list_checkin_users(kind: str, time_str: str, date: dt.date) -> list[tuple[int, int]]:
    with db_session() as session:
        if kind == "morning":
            rows = (
                session.query(User.id, User.tg_id)
                .filter(
                    User.morning_time == time_str,
                    (User.morning_last_date.is_(None)) | (User.morning_last_date != date),
                )
                .all()
            )
        else:
            rows = (
                session.query(User.id, User.tg_id)
                .filter(
                    User.evening_time == time_str,
                    (User.evening_last_date.is_(None)) | (User.evening_last_date != date),
                )
                .all()
            )
    return [(row[0], row[1]) for row in rows]


def list_reminder_users(kind: str) -> list[User]:
    with db_session() as session:
        if kind == "morning":
            return (
                session.query(User)
                .filter(User.morning_time.isnot(None), User.morning_time != "")
                .all()
            )
        return (
            session.query(User)
            .filter(User.evening_time.isnot(None), User.evening_time != "")
            .all()
        )


def list_weekly_review_users() -> list[User]:
    with db_session() as session:
        return (
            session.query(User)
            .filter(User.weekly_review_time.isnot(None), User.weekly_review_time != "")
            .all()
        )


def list_leaderboard_users() -> list[User]:
    with db_session() as session:
        return (
            session.query(User)
            .order_by(User.level.desc(), User.xp.desc(), User.tg_id.asc())
            .all()
        )


def leaderboard_display_name(user: User) -> str:
    parts = [p for p in [user.first_name, user.last_name] if p]
    if parts:
        return " ".join(parts)
    if user.username:
        return f"@{user.username}"
    return f"id {user.tg_id}"


def mark_weekly_review_sent(user_id: int, date: dt.date) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        user.weekly_review_last_date = date


def mark_checkin_sent(user_id: int, kind: str, date: dt.date) -> None:
    with db_session() as session:
        user = session.get(User, user_id)
        if not user:
            return
        if kind == "morning":
            user.morning_last_date = date
        else:
            user.evening_last_date = date


def get_mission(user_id: int, date: Optional[dt.date] = None) -> Mission:
    with db_session() as session:
        if date is None:
            user = session.get(User, user_id)
            tz = user.tz if user else "UTC"
            date = today_iso(tz)
        mission = (
            session.query(Mission)
            .filter(Mission.user_id == user_id, Mission.date == date)
            .one_or_none()
        )
        if not mission:
            mission = Mission(
                user_id=user_id,
                date=date,
                text="",
                status="not_set",
                done_def="",
                when_do="",
            )
            session.add(mission)
            session.flush()
        return mission


def update_mission(
    user_id: int,
    text: Optional[str] = None,
    status: Optional[str] = None,
    done_def: Optional[str] = None,
    when_do: Optional[str] = None,
    date: Optional[dt.date] = None,
) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        if date is None:
            user = session.get(User, user_id)
            tz = user.tz if user else "UTC"
            date = today_iso(tz)
        mission = (
            session.query(Mission)
            .filter(Mission.user_id == user_id, Mission.date == date)
            .one_or_none()
        )
        if not mission:
            mission = Mission(
                user_id=user_id,
                date=date,
                text="",
                status="not_set",
                done_def="",
                when_do="",
            )
            session.add(mission)
            session.flush()
        if text is not None:
            mission.text = text
        if status is not None:
            mission.status = status
        if done_def is not None:
            mission.done_def = done_def
        if when_do is not None:
            mission.when_do = when_do
        changed_user_id = mission.user_id
    if changed_user_id:
        request_google_sync(changed_user_id)


def list_trackers(user_id: int) -> list[Tracker]:
    with db_session() as session:
        return (
            session.query(Tracker)
            .filter(Tracker.user_id == user_id, Tracker.active.is_(True))
            .order_by(Tracker.order_index, Tracker.id)
            .all()
        )


def get_tracker(tracker_id: int) -> Optional[Tracker]:
    with db_session() as session:
        return session.get(Tracker, tracker_id)


def update_tracker(
    tracker_id: int,
    name: Optional[str] = None,
    type_: Optional[str] = None,
    xp: Optional[int] = None,
) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        changed_user_id = tracker.user_id
        if name is not None:
            tracker.name = name
        if type_ is not None:
            tracker.type = type_
            tracker.unit = "ч" if type_ == "time" else ""
            tracker.xp_count_map = None
            tracker.xp_scale_min = None
            tracker.xp_scale_max = None
        if xp is not None:
            tracker.xp = xp
    if changed_user_id:
        request_google_sync(changed_user_id)


def set_tracker_active(tracker_id: int, active: bool) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        tracker.active = active
        changed_user_id = tracker.user_id
    if changed_user_id:
        request_google_sync(changed_user_id)


def update_tracker_streak(
    tracker_id: int,
    enabled: Optional[bool] = None,
    mode: Optional[str] = None,
    period: Optional[str] = None,
    min_value: Optional[float] = None,
    partial_ok: Optional[bool] = None,
) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        changed_user_id = tracker.user_id
        if enabled is not None:
            tracker.streak_enabled = enabled
        if mode is not None:
            tracker.streak_mode = mode
        if period is not None:
            tracker.streak_period = period
        if min_value is not None:
            tracker.streak_min_value = min_value
        if partial_ok is not None:
            tracker.streak_partial_ok = partial_ok
    if changed_user_id:
        request_google_sync(changed_user_id)


def update_tracker_xp_rules(
    tracker_id: int,
    xp_count_map: Optional[str] = None,
    xp_scale_min: Optional[int] = None,
    xp_scale_max: Optional[int] = None,
) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        changed_user_id = tracker.user_id
        if xp_count_map is not None:
            tracker.xp_count_map = xp_count_map
        if xp_scale_min is not None:
            tracker.xp_scale_min = xp_scale_min
        if xp_scale_max is not None:
            tracker.xp_scale_max = xp_scale_max
    if changed_user_id:
        request_google_sync(changed_user_id)


def add_tracker(
    user_id: int,
    name: str,
    type_: str,
    difficulty: str = "medium",
    xp: int = 10,
    period: str = "day",
    target: int = 0,
    unit: str = "",
    days: str = "Пн,Вт,Ср,Чт,Пт,Сб,Вс",
    xp_count_map: Optional[str] = None,
    xp_scale_min: Optional[int] = None,
    xp_scale_max: Optional[int] = None,
) -> int:
    with db_session() as session:
        tracker = Tracker(
            user_id=user_id,
            name=name,
            type=type_,
            difficulty=difficulty,
            xp=xp,
            period=period,
            target=target,
            unit=unit,
            days=days,
            active=True,
            streak_enabled=True,
            streak_partial_ok=True,
            order_index=int(dt.datetime.utcnow().timestamp()),
            xp_count_map=xp_count_map,
            xp_scale_min=xp_scale_min,
            xp_scale_max=xp_scale_max,
        )
        session.add(tracker)
        session.flush()
        tracker_id = tracker.id
    return tracker_id
    request_google_sync(user_id)


def tracker_progress(tracker_id: int, date: dt.date) -> Tuple[float, bool]:
    with db_session() as session:
        total, partial_int = (
            session.query(
                func.coalesce(func.sum(TrackerLog.value), 0),
                func.coalesce(
                    func.max(case((TrackerLog.partial.is_(True), 1), else_=0)),
                    0,
                ),
            )
            .filter(TrackerLog.tracker_id == tracker_id, TrackerLog.date == date)
            .one()
        )
        return float(total or 0), bool(partial_int)


def period_range(period: str, date: dt.date) -> tuple[dt.date, dt.date]:
    if period == "day":
        start = date
        end = date
    elif period == "week":
        start = date - dt.timedelta(days=date.weekday())
        end = start + dt.timedelta(days=6)
    elif period == "month":
        start = date.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - dt.timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - dt.timedelta(days=1)
    else:  # year
        start = date.replace(month=1, day=1)
        end = date.replace(month=12, day=31)
    return start, end


def tracker_progress_period(tracker_id: int, period: str, date: dt.date) -> float:
    start, end = period_range(period, date)
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return 0.0
        aggregate = func.avg if tracker.type == "scale" else func.sum
        total = (
            session.query(func.coalesce(aggregate(TrackerLog.value), 0))
            .filter(
                TrackerLog.tracker_id == tracker_id,
                TrackerLog.date >= start,
                TrackerLog.date <= end,
            )
            .scalar()
        )
        return float(total or 0)


def tracker_progress_range(tracker_id: int, start: dt.date, end: dt.date) -> float:
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return 0.0
        aggregate = func.avg if tracker.type == "scale" else func.sum
        total = (
            session.query(func.coalesce(aggregate(TrackerLog.value), 0))
            .filter(
                TrackerLog.tracker_id == tracker_id,
                TrackerLog.date >= start,
                TrackerLog.date <= end,
            )
            .scalar()
        )
        return float(total or 0)


def tracker_activity_success(tracker: Tracker, start: dt.date, end: dt.date) -> bool:
    if tracker.type == "binary":
        partial_ok = True if tracker.streak_partial_ok is None else tracker.streak_partial_ok
        with db_session() as session:
            if partial_ok:
                count = (
                    session.query(func.count(TrackerLog.id))
                    .filter(
                        TrackerLog.tracker_id == tracker.id,
                        TrackerLog.date >= start,
                        TrackerLog.date <= end,
                    )
                    .scalar()
                )
            else:
                count = (
                    session.query(func.count(TrackerLog.id))
                    .filter(
                        TrackerLog.tracker_id == tracker.id,
                        TrackerLog.date >= start,
                        TrackerLog.date <= end,
                        TrackerLog.partial.is_(False),
                    )
                    .scalar()
                )
        return bool(count and count > 0)

    total = tracker_progress_range(tracker.id, start, end)
    threshold = tracker.streak_min_value or 0
    if threshold <= 0:
        return total > 0
    return total >= threshold


def tracker_goal_success(tracker: Tracker, start: dt.date, end: dt.date, period: str) -> bool:
    goals = get_tracker_goals(tracker.id)
    target = goals.get(period, 0)
    if not target or target <= 0:
        return False
    total = tracker_progress_range(tracker.id, start, end)
    return total >= target


def tracker_streak_value(tracker: Tracker, date: dt.date) -> int:
    if tracker.streak_enabled is False:
        return 0
    mode = tracker.streak_mode or "activity"
    period = tracker.streak_period or ("week" if mode == "goal" else "day")
    if mode == "goal" and period not in {"week", "month", "year"}:
        return 0
    if mode != "goal" and period not in {"day", "week", "month"}:
        period = "day"
    streak = 0
    current = date
    for _ in range(366):
        start, end = period_range(period, current)
        success = (
            tracker_goal_success(tracker, start, end, period)
            if mode == "goal"
            else tracker_activity_success(tracker, start, end)
        )
        if not success:
            break
        streak += 1
        current = start - dt.timedelta(days=1)
    return streak


def superscript_number(value: int) -> str:
    digits = "0123456789"
    supers = "⁰¹²³⁴⁵⁶⁷⁸⁹"
    return "".join(supers[digits.index(ch)] for ch in str(value))


def tracker_streak_value_display(tracker: Tracker, date: dt.date) -> int:
    streak = tracker_streak_value(tracker, date)
    if streak > 0:
        return streak
    if tracker.streak_enabled is False:
        return 0
    mode = tracker.streak_mode or "activity"
    period = tracker.streak_period or ("week" if mode == "goal" else "day")
    if mode == "goal" and period not in {"week", "month", "year"}:
        return 0
    if mode != "goal" and period not in {"day", "week", "month"}:
        period = "day"
    start, end = period_range(period, date)
    if mode == "goal":
        if tracker_goal_success(tracker, start, end, period):
            return streak
    else:
        if tracker_activity_success(tracker, start, end):
            return streak
    prev_date = start - dt.timedelta(days=1)
    return tracker_streak_value(tracker, prev_date)


def tracker_streak_suffix(tracker: Tracker, date: dt.date) -> str:
    streak = tracker_streak_value_display(tracker, date)
    if streak <= 0:
        return ""
    return f" ❤️‍🔥{superscript_number(streak)}"


def get_tracker_goals(tracker_id: int) -> dict[str, float]:
    with db_session() as session:
        rows = (
            session.query(TrackerGoal)
            .filter(TrackerGoal.tracker_id == tracker_id)
            .all()
        )
        return {r.period: float(r.target) for r in rows}


def set_tracker_goal(tracker_id: int, period: str, target: float) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if tracker:
            changed_user_id = tracker.user_id
        goal = (
            session.query(TrackerGoal)
            .filter(TrackerGoal.tracker_id == tracker_id, TrackerGoal.period == period)
            .one_or_none()
        )
        if goal:
            goal.target = target
        else:
            session.add(TrackerGoal(tracker_id=tracker_id, period=period, target=target))
        display = (
            session.query(TrackerGoalDisplay)
            .filter(TrackerGoalDisplay.tracker_id == tracker_id)
            .one_or_none()
        )
        if not display:
            session.add(
                TrackerGoalDisplay(
                    tracker_id=tracker_id, period=period, format="progress_goal"
                )
            )
    if changed_user_id:
        request_google_sync(changed_user_id)


def get_tracker_display(tracker_id: int) -> Optional[TrackerGoalDisplay]:
    with db_session() as session:
        return (
            session.query(TrackerGoalDisplay)
            .filter(TrackerGoalDisplay.tracker_id == tracker_id)
            .one_or_none()
        )


def set_tracker_display(tracker_id: int, period: str, format_: str) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if tracker:
            changed_user_id = tracker.user_id
        row = (
            session.query(TrackerGoalDisplay)
            .filter(TrackerGoalDisplay.tracker_id == tracker_id)
            .one_or_none()
        )
        if row:
            row.period = period
            row.format = format_
        else:
            session.add(
                TrackerGoalDisplay(tracker_id=tracker_id, period=period, format=format_)
            )
    if changed_user_id:
        request_google_sync(changed_user_id)


def format_value(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def tracker_type_label(type_value: Optional[str]) -> str:
    labels = {
        "binary": "да/нет",
        "time": "время",
        "count": "количество",
        "scale": "шкала 1–10",
    }
    return labels.get(type_value or "", type_value or "—")


def tracker_display_label(tracker: Tracker, date: dt.date) -> Optional[str]:
    display = get_tracker_display(tracker.id)
    goals = get_tracker_goals(tracker.id)
    if not display:
        for p in ("week", "month", "year"):
            if goals.get(p, 0) > 0:
                display = TrackerGoalDisplay(tracker_id=tracker.id, period=p, format="progress_goal")
                break
    if not display:
        return None
    target = goals.get(display.period)
    if not target:
        return None
    progress = tracker_progress_period(tracker.id, display.period, date)
    unit = tracker.unit or ""
    progress_s = f"{format_value(progress)}{unit}"
    target_s = f"{format_value(target)}{unit}"
    if display.format == "progress_goal":
        return f"{tracker.name}: {progress_s}/{target_s}"
    if display.format == "progress":
        return f"{tracker.name}: {progress_s}"
    if display.format == "goal":
        return f"{tracker.name}: цель {target_s}"
    if display.format == "percent":
        pct = int((progress / target) * 100) if target else 0
        return f"{tracker.name}: {pct}%"
    return None


def log_tracker(tracker_id: int, date: dt.date, value: float, partial: bool = False) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if not tracker:
            return
        changed_user_id = tracker.user_id
        session.add(
            TrackerLog(
                tracker_id=tracker_id,
                date=date,
                value=value,
                partial=partial,
            )
        )
    if changed_user_id:
        request_google_sync(changed_user_id)


def clear_tracker_logs(tracker_id: int, date: dt.date) -> None:
    changed_user_id: Optional[int] = None
    with db_session() as session:
        tracker = session.get(Tracker, tracker_id)
        if tracker:
            changed_user_id = tracker.user_id
        session.query(TrackerLog).filter(
            TrackerLog.tracker_id == tracker_id,
            TrackerLog.date == date,
        ).delete()
    if changed_user_id:
        request_google_sync(changed_user_id)


def get_journal_entry(user_id: int, date: dt.date) -> Optional[JournalEntry]:
    with db_session() as session:
        return (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id, JournalEntry.date == date)
            .one_or_none()
        )


def list_journal_entries(user_id: int, limit: int, offset: int = 0) -> list[JournalEntry]:
    with db_session() as session:
        return (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id)
            .order_by(JournalEntry.date.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


def count_journal_entries(user_id: int) -> int:
    with db_session() as session:
        return (
            session.query(func.count(JournalEntry.id))
            .filter(JournalEntry.user_id == user_id)
            .scalar()
            or 0
        )


def list_weekly_reports(user_id: int, limit: int, offset: int = 0) -> list[JournalWeeklyReport]:
    with db_session() as session:
        return (
            session.query(JournalWeeklyReport)
            .filter(JournalWeeklyReport.user_id == user_id)
            .order_by(JournalWeeklyReport.week_start.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )


def count_weekly_reports(user_id: int) -> int:
    with db_session() as session:
        return (
            session.query(func.count(JournalWeeklyReport.id))
            .filter(JournalWeeklyReport.user_id == user_id)
            .scalar()
            or 0
        )


def list_journal_entries_range(
    user_id: int, start: dt.date, end: dt.date
) -> list[JournalEntry]:
    with db_session() as session:
        return (
            session.query(JournalEntry)
            .filter(
                JournalEntry.user_id == user_id,
                JournalEntry.date >= start,
                JournalEntry.date <= end,
            )
            .order_by(JournalEntry.date.asc())
            .all()
        )


def list_all_journal_entries(user_id: int) -> list[JournalEntry]:
    with db_session() as session:
        return (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id)
            .order_by(JournalEntry.date.asc())
            .all()
        )


def get_weekly_report(user_id: int, week_start: dt.date) -> Optional[JournalWeeklyReport]:
    with db_session() as session:
        return (
            session.query(JournalWeeklyReport)
            .filter(
                JournalWeeklyReport.user_id == user_id,
                JournalWeeklyReport.week_start == week_start,
            )
            .one_or_none()
        )


def save_weekly_report(
    user_id: int, week_start: dt.date, week_end: dt.date, text: str, model: Optional[str]
) -> JournalWeeklyReport:
    with db_session() as session:
        report = JournalWeeklyReport(
            user_id=user_id,
            week_start=week_start,
            week_end=week_end,
            analysis_text=text,
            model=model,
        )
        session.add(report)
        session.flush()
        report_id = report.id
    request_google_sync(user_id)
    with db_session() as session:
        return session.get(JournalWeeklyReport, report_id)


def list_coach_messages(user_id: int) -> list[CoachMessage]:
    with db_session() as session:
        return (
            session.query(CoachMessage)
            .filter(CoachMessage.user_id == user_id)
            .order_by(CoachMessage.created_at.asc(), CoachMessage.id.asc())
            .all()
        )


def save_coach_message(
    user_id: int, role: str, content: str, report_id: Optional[int] = None
) -> None:
    with db_session() as session:
        session.add(
            CoachMessage(
                user_id=user_id,
                report_id=report_id,
                role=role,
                content=content,
            )
        )


def start_journal_entry(user_id: int, date: dt.date) -> JournalEntry:
    now = _utcnow()
    with db_session() as session:
        entry = (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id, JournalEntry.date == date)
            .one_or_none()
        )
        if entry:
            entry.status = "open"
            entry.auto_closed = False
            entry.closed_at = None
            entry.updated_at = now
        else:
            entry = JournalEntry(
                user_id=user_id,
                date=date,
                text="",
                status="open",
                created_at=now,
                updated_at=now,
            )
            session.add(entry)
            session.flush()
        return entry


def append_journal_message(
    entry_id: int,
    user_id: int,
    message_type: str,
    text: Optional[str] = None,
    transcript: Optional[str] = None,
    tg_file_id: Optional[str] = None,
    duration_sec: Optional[int] = None,
) -> Optional[JournalEntry]:
    now = _utcnow()
    content = (transcript or text or "").strip()
    with db_session() as session:
        entry = session.get(JournalEntry, entry_id)
        if not entry:
            return None
        if content:
            if entry.text:
                entry.text = entry.text.rstrip() + "\n" + content
            else:
                entry.text = content
        entry.status = "open"
        entry.auto_closed = False
        entry.closed_at = None
        entry.last_message_at = now
        entry.updated_at = now
        session.add(
            JournalMessage(
                entry_id=entry_id,
                user_id=user_id,
                message_type=message_type,
                text=text,
                transcript=transcript,
                tg_file_id=tg_file_id,
                duration_sec=duration_sec,
            )
        )
        session.flush()
        entry_id = entry.id
    request_google_sync(user_id)
    return entry


def close_journal_entry(entry_id: int, auto_closed: bool = False) -> Optional[int]:
    user_id: Optional[int] = None
    now = _utcnow()
    with db_session() as session:
        entry = session.get(JournalEntry, entry_id)
        if not entry:
            return None
        entry.status = "closed"
        entry.closed_at = now
        entry.auto_closed = auto_closed
        entry.updated_at = now
        user_id = entry.user_id
    if user_id:
        request_google_sync(user_id)
    return user_id


def clear_journal_entry(user_id: int, date: dt.date) -> None:
    now = _utcnow()
    with db_session() as session:
        entry = (
            session.query(JournalEntry)
            .filter(JournalEntry.user_id == user_id, JournalEntry.date == date)
            .one_or_none()
        )
        if not entry:
            return
        session.query(JournalMessage).filter(JournalMessage.entry_id == entry.id).delete()
        entry.text = ""
        entry.status = "closed"
        entry.closed_at = now
        entry.last_message_at = None
        entry.auto_closed = False
        entry.updated_at = now
    request_google_sync(user_id)


def list_stale_journal_entries(cutoff: dt.datetime) -> list[tuple[int, int, int]]:
    with db_session() as session:
        rows = (
            session.query(JournalEntry.id, JournalEntry.user_id, User.tg_id)
            .join(User, User.id == JournalEntry.user_id)
            .filter(
                JournalEntry.status == "open",
                JournalEntry.last_message_at.isnot(None),
                JournalEntry.last_message_at < cutoff,
            )
            .all()
        )
    return [(row[0], row[1], row[2]) for row in rows]


def get_journal_text(user_id: int, date: dt.date) -> str:
    entry = get_journal_entry(user_id, date)
    return entry.text if entry else ""


# ----------------------------
# Keyboards
# ----------------------------
def main_reply_kb(tg_id: Optional[int] = None) -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text="🏠 Сегодня"),
            KeyboardButton(text="Настройки трекеров"),
            KeyboardButton(text="🗒 Дневник"),
        ],
        [
            KeyboardButton(text="🏆 Лидерборд"),
            KeyboardButton(text="⚙️ Настройки"),
        ],
    ]
    web_url = build_webapp_url(tg_id)
    if web_url:
        rows.append([KeyboardButton(text="📊 Аналитика", web_app=WebAppInfo(url=web_url))])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
    )


def retro_dates_inline(user_tz: str, days: int = 7) -> InlineKeyboardMarkup:
    today = today_iso(user_tz)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for offset in range(days):
        date = today - dt.timedelta(days=offset)
        if offset == 0:
            label = "Сегодня"
        elif offset == 1:
            label = "Вчера"
        else:
            label = f"{offset} дн. назад"
        label = f"{label} ({date.strftime('%d.%m')})"
        row.append(InlineKeyboardButton(text=label, callback_data=f"tracker:retro_date:{date.isoformat()}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="📅 Другая дата", callback_data="tracker:retro_manual")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="tracker:retro_exit")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🕒 Часовой пояс", callback_data="settings:timezone")],
            [InlineKeyboardButton(text="☀️ Утренний чек-ин", callback_data="settings:morning")],
            [InlineKeyboardButton(text="🌙 Вечерний чек-ин", callback_data="settings:evening")],
            [InlineKeyboardButton(text="🤖 ИИ коуч", callback_data="settings:coach")],
            [InlineKeyboardButton(text="📊 Google Sheets", callback_data="settings:google")],
        ]
    )


def mission_inline(status: str) -> InlineKeyboardMarkup:
    buttons = []
    if status == "not_set":
        buttons.append(
            [InlineKeyboardButton(text="🎯 Задать миссию", callback_data="mission:set")]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(text="✅ Сделано", callback_data="mission:done"),
                InlineKeyboardButton(text="↩️ Частично", callback_data="mission:partial"),
                InlineKeyboardButton(text="❌ Не сделал", callback_data="mission:fail"),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(text="✏️ Править", callback_data="mission:set"),
                InlineKeyboardButton(text="🕒 Когда", callback_data="mission:when"),
                InlineKeyboardButton(text="✅ Done def", callback_data="mission:done_def"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def evening_checkin_inline(user_tg_id: int) -> InlineKeyboardMarkup:
    _, kb = render_today_view(user_tg_id)
    rows = list(kb.inline_keyboard)
    rows.append([InlineKeyboardButton(text="🗒 Перейти к дневнику", callback_data="journal:start")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tracker_inline(tracker: Tracker, date: dt.date) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    total, partial = tracker_progress(tracker.id, date)
    if tracker.type == "binary":
        label = "✅ Отметить" if total == 0 else "↩️ Отменить"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"tracker:toggle:{tracker.id}")]
        )
        buttons.append(
            [
                InlineKeyboardButton(text="↩️ Частично", callback_data=f"tracker:partial:{tracker.id}"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"tracker:card:{tracker.id}"),
            ]
        )
    elif tracker.type == "count":
        buttons.extend(count_value_buttons(tracker))
        buttons.append(
            [
                InlineKeyboardButton(text="Ввести число", callback_data=f"tracker:custom:{tracker.id}"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"tracker:card:{tracker.id}"),
            ]
        )
    elif tracker.type == "time":
        buttons.append(
            [
                InlineKeyboardButton(text="+1", callback_data=f"tracker:add:{tracker.id}:1"),
                InlineKeyboardButton(text="+5", callback_data=f"tracker:add:{tracker.id}:5"),
                InlineKeyboardButton(text="+10", callback_data=f"tracker:add:{tracker.id}:10"),
            ]
        )
        buttons.append(
            [
                InlineKeyboardButton(text="Ввести число", callback_data=f"tracker:custom:{tracker.id}"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"tracker:card:{tracker.id}"),
            ]
        )
    else:
        # scale 1-10
        row = [
            InlineKeyboardButton(text=str(v), callback_data=f"tracker:add:{tracker.id}:{v}")
            for v in [6, 7, 8, 9, 10]
        ]
        buttons.append(row)
        buttons.append(
            [
                InlineKeyboardButton(text="✏️ Коммент", callback_data=f"tracker:custom:{tracker.id}"),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=f"tracker:card:{tracker.id}"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def trackers_menu(trackers: list[Tracker], date: dt.date) -> list[str]:
    lines = []
    for t in trackers:
        label = tracker_display_label(t, date)
        if label:
            lines.append(f"{label}{tracker_streak_suffix(t, date)}")
            continue
        total, partial = tracker_progress(t.id, date)
        if t.type == "binary":
            marker = "✅" if total else ("↩️" if partial else "☑️")
            lines.append(f"{marker} {t.name} (XP {t.xp}){tracker_streak_suffix(t, date)}")
        elif t.type in {"time", "count"}:
            unit = t.unit or ""
            lines.append(f"{t.name}: {int(total)}/{t.target}{unit} ({t.period}){tracker_streak_suffix(t, date)}")
        else:
            lines.append(f"{t.name}: {total or '—'}/10{tracker_streak_suffix(t, date)}")
    return lines


def tracker_list_inline(trackers: list[Tracker]) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"{t.name} ({tracker_type_label(t.type)})",
                callback_data=f"tracker:card:{t.id}",
            )
        ]
        for t in trackers
    ]
    buttons.append([InlineKeyboardButton(text="🕓 Заполнить прошлые дни", callback_data="tracker:retro_menu")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="tracker:add_new")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def tracker_card_inline(tracker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"tracker:edit:{tracker_id}")],
            [InlineKeyboardButton(text="❤️‍🔥 Стрик", callback_data=f"tracker:streak:{tracker_id}")],
            [InlineKeyboardButton(text="🎯 Цели", callback_data=f"goal:open:{tracker_id}")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"tracker:delete:{tracker_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="goal:back")],
        ]
    )


def tracker_delete_confirm_inline(tracker_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"tracker:delete_confirm:{tracker_id}")],
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"tracker:card:{tracker_id}")],
        ]
    )


def tracker_edit_inline(tracker_id: int) -> InlineKeyboardMarkup:
    tracker = get_tracker(tracker_id)
    xp_label = "🎯 XP"
    if tracker:
        if tracker.type == "count":
            xp_label = "🎯 XP правила"
        elif tracker.type == "scale":
            xp_label = "🎯 XP шкалы"
        elif tracker.type == "time":
            xp_label = "🎯 XP/час"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя", callback_data=f"tracker:edit_name:{tracker_id}")],
            [InlineKeyboardButton(text="🔁 Тип", callback_data=f"tracker:edit_type_menu:{tracker_id}")],
            [InlineKeyboardButton(text=xp_label, callback_data=f"tracker:edit_xp:{tracker_id}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tracker:card:{tracker_id}")],
        ]
    )


def tracker_edit_type_inline(tracker_id: int, current_type: str) -> InlineKeyboardMarkup:
    labels = {
        "binary": "Бинарный",
        "time": "Время",
        "count": "Количество",
        "scale": "Шкала 1–10",
    }
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if current_type == "binary" else "") + labels["binary"],
                callback_data=f"tracker:edit_type:{tracker_id}:binary",
            ),
            InlineKeyboardButton(
                text=("✅ " if current_type == "time" else "") + labels["time"],
                callback_data=f"tracker:edit_type:{tracker_id}:time",
            ),
        ],
        [
            InlineKeyboardButton(
                text=("✅ " if current_type == "count" else "") + labels["count"],
                callback_data=f"tracker:edit_type:{tracker_id}:count",
            ),
            InlineKeyboardButton(
                text=("✅ " if current_type == "scale" else "") + labels["scale"],
                callback_data=f"tracker:edit_type:{tracker_id}:scale",
            ),
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tracker:edit:{tracker_id}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tracker_streak_inline(tracker: Tracker) -> InlineKeyboardMarkup:
    enabled = True if tracker.streak_enabled is None else tracker.streak_enabled
    mode = tracker.streak_mode or "activity"
    period = tracker.streak_period or ("week" if mode == "goal" else "day")
    toggle_label = "✅ Включен" if enabled else "🚫 Выключен"
    mode_labels = {"activity": "По отметкам", "goal": "По цели"}
    period_labels = {
        "day": "День",
        "week": "Неделя",
        "month": "Месяц",
        "year": "Год",
    }
    mode_buttons = [
        InlineKeyboardButton(
            text=("✅ " if mode == key else "") + mode_labels[key],
            callback_data=f"tracker:streak_mode:{tracker.id}:{key}",
        )
        for key in ["activity", "goal"]
    ]
    if mode == "goal":
        period_keys = ["week", "month", "year"]
    else:
        period_keys = ["day", "week", "month"]
    period_buttons = [
        InlineKeyboardButton(
            text=("✅ " if period == key else "") + period_labels[key],
            callback_data=f"tracker:streak_period:{tracker.id}:{key}",
        )
        for key in period_keys
    ]
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=toggle_label, callback_data=f"tracker:streak_toggle:{tracker.id}")],
        mode_buttons,
        period_buttons,
    ]
    if mode == "activity":
        if tracker.type == "binary":
            partial_ok = True if tracker.streak_partial_ok is None else tracker.streak_partial_ok
            partial_label = "Частично: да" if partial_ok else "Частично: нет"
            rows.append(
                [InlineKeyboardButton(text=partial_label, callback_data=f"tracker:streak_partial:{tracker.id}")]
            )
        else:
            rows.append(
                [InlineKeyboardButton(text="Мин. значение", callback_data=f"tracker:streak_min:{tracker.id}")]
            )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tracker:card:{tracker.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def tracker_goals_inline(tracker_id: int) -> InlineKeyboardMarkup:
    tracker = get_tracker(tracker_id)
    if tracker and tracker.type == "scale":
        week_label = "Неделя (ср. 1–10)"
        month_label = "Месяц (ср. 1–10)"
        year_label = "Год (ср. 1–10)"
    else:
        week_label = "Неделя"
        month_label = "Месяц"
        year_label = "Год"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=week_label, callback_data=f"goal:set:{tracker_id}:week"),
                InlineKeyboardButton(text=month_label, callback_data=f"goal:set:{tracker_id}:month"),
                InlineKeyboardButton(text=year_label, callback_data=f"goal:set:{tracker_id}:year"),
            ],
            [
                InlineKeyboardButton(
                    text="Что показывать в кнопке", callback_data=f"goal:display:{tracker_id}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tracker:card:{tracker_id}")],
        ]
    )


def tracker_display_inline(tracker_id: int, period: str, format_: str) -> InlineKeyboardMarkup:
    period_labels = {"week": "Неделя", "month": "Месяц", "year": "Год"}
    format_labels = {
        "progress_goal": "Прогресс/цель",
        "progress": "Только прогресс",
        "goal": "Только цель",
        "percent": "Процент",
    }
    p_buttons = [
        InlineKeyboardButton(
            text=("✅ " if period == key else "") + label,
            callback_data=f"goal:display_period:{tracker_id}:{key}",
        )
        for key, label in period_labels.items()
    ]
    f_buttons = [
        InlineKeyboardButton(
            text=("✅ " if format_ == key else "") + label,
            callback_data=f"goal:display_format:{tracker_id}:{key}",
        )
        for key, label in format_labels.items()
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            p_buttons,
            f_buttons[:2],
            f_buttons[2:],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"goal:open:{tracker_id}")],
        ]
    )


def goal_value_prompt(tracker: Tracker, period: str) -> str:
    period_label = {"week": "неделю", "month": "месяц", "year": "год"}.get(period, period)
    if tracker.type == "scale":
        return (
            f"Цель на {period_label} — средняя оценка за период. "
            "Введи число 1–10 (например 7)."
        )
    unit_hint = "в часах " if tracker.type == "time" else ""
    return f"Цель на {period_label} ({unit_hint}число):"


def _journal_entry_label(entry: JournalEntry) -> str:
    date_label = entry.date.strftime("%d.%m.%Y")
    status = "✅" if entry.status == "closed" and entry.text else "📝"
    return f"{status} {date_label}"


def journal_menu_inline(entries: list[JournalEntry]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="✍️ Сегодня", callback_data="journal:start"),
            InlineKeyboardButton(text="🗑 Очистить", callback_data="journal:clear_today"),
        ],
        [
            InlineKeyboardButton(text="📚 История", callback_data="journal:list:0"),
            InlineKeyboardButton(text="🧠 Отчеты недели", callback_data="journal:reports:0"),
        ],
    ]
    for entry in entries:
        rows.append(
            [InlineKeyboardButton(text=_journal_entry_label(entry), callback_data=f"journal:view:{entry.id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def journal_entries_inline(entries: list[JournalEntry], offset: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for entry in entries:
        rows.append(
            [InlineKeyboardButton(text=_journal_entry_label(entry), callback_data=f"journal:view:{entry.id}")]
        )
    nav = []
    if offset > 0:
        prev_offset = max(0, offset - JOURNAL_PAGE_SIZE)
        nav.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"journal:list:{prev_offset}"))
    if offset + JOURNAL_PAGE_SIZE < total:
        next_offset = offset + JOURNAL_PAGE_SIZE
        nav.append(InlineKeyboardButton(text="➡️ Далее", callback_data=f"journal:list:{next_offset}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="journal:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _weekly_report_label(report: JournalWeeklyReport) -> str:
    start = report.week_start.strftime("%d.%m")
    end = report.week_end.strftime("%d.%m")
    return f"🧠 Неделя {start}–{end}"


def journal_reports_inline(
    reports: list[JournalWeeklyReport], offset: int, total: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for report in reports:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_weekly_report_label(report), callback_data=f"journal:report:{report.id}"
                )
            ]
        )
    nav = []
    if offset > 0:
        prev_offset = max(0, offset - REPORT_PAGE_SIZE)
        nav.append(
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"journal:reports:{prev_offset}")
        )
    if offset + REPORT_PAGE_SIZE < total:
        next_offset = offset + REPORT_PAGE_SIZE
        nav.append(
            InlineKeyboardButton(text="➡️ Далее", callback_data=f"journal:reports:{next_offset}")
        )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Меню", callback_data="journal:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def journal_collect_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✅ Завершить заметку", callback_data="journal:finish")]]
    )


def _journal_ack_text(pending_count: int, transcript_failed: bool) -> str:
    count = pending_count if pending_count > 0 else 1
    if transcript_failed:
        if count <= 1:
            return (
                "Голосовое сообщение сохранено, но транскрипцию получить не удалось. "
                "Можешь отправить еще или завершить заметку."
            )
        return (
            "Сообщения сохранены, но часть голосовых без транскрипции. "
            "Можешь отправить еще или завершить заметку."
        )
    if count <= 1:
        return "Сообщение сохранено. Можешь отправить еще или завершить заметку."
    return "Сообщения сохранены. Можешь отправить еще или завершить заметку."


def cancel_journal_ack(chat_id: int) -> None:
    task = _journal_ack_tasks.pop(chat_id, None)
    if task and not task.done():
        task.cancel()


async def _journal_ack_worker(bot: Bot, chat_id: int, state: FSMContext) -> None:
    task = asyncio.current_task()
    try:
        await asyncio.sleep(JOURNAL_ACK_DEBOUNCE_SEC)
        if await state.get_state() != JournalStates.collecting.state:
            return
        data = await state.get_data()
        if not data.get("journal_entry_id"):
            return
        pending_count = int(data.get("journal_pending_count") or 0)
        transcript_failed = bool(data.get("journal_transcript_failed"))
        text = _journal_ack_text(pending_count, transcript_failed)
        await bot.send_message(chat_id, text, reply_markup=journal_collect_inline())
        await state.update_data(journal_pending_count=0, journal_transcript_failed=False)
    except asyncio.CancelledError:
        return
    finally:
        if task and _journal_ack_tasks.get(chat_id) is task:
            _journal_ack_tasks.pop(chat_id, None)


async def schedule_journal_ack(
    bot: Bot, chat_id: int, state: FSMContext, transcript_failed: bool = False
) -> None:
    data = await state.get_data()
    pending_count = int(data.get("journal_pending_count") or 0) + 1
    updates = {"journal_pending_count": pending_count}
    if transcript_failed:
        updates["journal_transcript_failed"] = True
    await state.update_data(**updates)
    cancel_journal_ack(chat_id)
    task = asyncio.create_task(_journal_ack_worker(bot, chat_id, state))
    _journal_ack_tasks[chat_id] = task


def coach_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⏹ Завершить", callback_data="coach:stop")]]
    )


# ----------------------------
# View helpers
# ----------------------------
def settings_text(user: User) -> str:
    morning = user.morning_time or "не задано"
    evening = user.evening_time or "не задано"
    sheet = user.google_sheet_url or "не подключено"
    tz_label = user.tz or "UTC"
    weekly_time = user.weekly_review_time or "выкл"
    return (
        "⚙️ Настройки\n"
        f"Часовой пояс: {tz_label}\n"
        f"Утро: {morning}\n"
        f"Вечер: {evening}\n"
        f"Анализ недели: вс {weekly_time}\n\n"
        f"Google Sheets: {sheet}\n\n"
        "Формат времени: 08:30"
    )


def _shorten_text(text: str, limit: int = 240) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _truncate_for_tg(text: str, limit: int = 3500) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def journal_menu_text(user: User, entry: Optional[JournalEntry]) -> str:
    date_label = today_iso(user.tz).strftime("%d.%m.%Y")
    if not entry or not entry.text:
        preview = "(пусто)"
    else:
        preview = _shorten_text(entry.text)
    status = "открыта" if entry and entry.status == "open" else "закрыта"
    return (
        "🗒 Дневник\n"
        f"Сегодня ({date_label}): {status}\n\n"
        f"{preview}\n\n"
        "Ниже — быстрый доступ к последним заметкам."
    )


def coach_settings_text(user: User) -> str:
    prompt = user.coach_prompt or DEFAULT_COACH_PROMPT
    prompt_preview = _shorten_text(prompt, 300) if prompt else "(пусто)"
    weekly_time = user.weekly_review_time or "выкл"
    return (
        "🤖 ИИ коуч\n"
        f"Анализ недели: вс {weekly_time}\n\n"
        "Промпт:\n"
        f"{prompt_preview}\n\n"
        "Что изменить?"
    )


def coach_settings_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📝 Промпт", callback_data="settings:coach_prompt")],
            [InlineKeyboardButton(text="🕒 Время анализа", callback_data="settings:weekly_time")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="settings:back")],
        ]
    )


def tracker_input_prompt(tracker: Tracker, date: dt.date) -> tuple[str, InlineKeyboardMarkup]:
    total, _ = tracker_progress(tracker.id, date)
    name = tracker.name
    if tracker.type == "scale":
        text = f"{name}: выбери оценку 1–10. Сейчас: {total or '—'}"
        buttons = []
        for chunk in [range(1, 6), range(6, 11)]:
            buttons.append(
                [
                    InlineKeyboardButton(text=str(v), callback_data=f"tracker:add:{tracker.id}:{v}")
                    for v in chunk
                ]
            )
        return text, InlineKeyboardMarkup(inline_keyboard=buttons)

    # time / count
    unit = tracker.unit or ""
    text = f"{name}: добавить значение. Прогресс: {int(total)}/{tracker.target}{unit}"
    if tracker.type == "count":
        buttons = count_value_buttons(tracker)
        buttons.append(
            [InlineKeyboardButton(text="✍️ Ввести число", callback_data=f"tracker:custom:{tracker.id}")]
        )
    else:
        buttons = [
            [
                InlineKeyboardButton(text="+1", callback_data=f"tracker:add:{tracker.id}:1"),
                InlineKeyboardButton(text="+5", callback_data=f"tracker:add:{tracker.id}:5"),
                InlineKeyboardButton(text="+10", callback_data=f"tracker:add:{tracker.id}:10"),
            ],
            [InlineKeyboardButton(text="✍️ Ввести число", callback_data=f"tracker:custom:{tracker.id}")],
        ]
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def tracker_card_text(tracker: Tracker) -> str:
    goals = get_tracker_goals(tracker.id)
    unit = tracker.unit or ""

    def goal_line(label: str, key: str) -> str:
        value = goals.get(key)
        if value and value > 0:
            return f"{label}: {format_value(value)}{unit}"
        return f"{label}: нет"

    goals_text = "\n".join(
        [
            goal_line("Неделя", "week"),
            goal_line("Месяц", "month"),
            goal_line("Год", "year"),
        ]
    )
    xp_label = "XP за 1 час" if tracker.type == "time" else "XP"
    streak_value = tracker_streak_value(tracker, today_iso())
    enabled = True if tracker.streak_enabled is None else tracker.streak_enabled
    streak_text = f"❤️‍🔥 Стрик: {streak_value}" if enabled else "❤️‍🔥 Стрик: выкл"
    xp_text = ""
    if tracker.type == "count":
        mapping = load_count_xp_map(tracker)
        xp_text = f"XP правила: {format_count_xp_map(mapping)}" if mapping else "XP правила: нет"
    elif tracker.type == "scale":
        if tracker.xp_scale_min is not None and tracker.xp_scale_max is not None:
            xp_text = f"XP шкала: {tracker.xp_scale_min}–{tracker.xp_scale_max}"
        else:
            xp_text = "XP шкала: нет"
    else:
        xp_text = f"{xp_label}: {tracker.xp}"
    return (
        f"⚙️ Трекер: {tracker.name}\n"
        f"Тип: {tracker_type_label(tracker.type)}\n"
        f"{xp_text}\n"
        f"{streak_text}\n"
        f"Цели:\n{goals_text}"
    )


def tracker_edit_text(tracker: Tracker) -> str:
    xp_label = "XP за 1 час" if tracker.type == "time" else "XP"
    streak_status = "вкл" if tracker.streak_enabled is not False else "выкл"
    mode_label = "по отметкам" if tracker.streak_mode != "goal" else "по цели"
    period_value = tracker.streak_period or ("week" if tracker.streak_mode == "goal" else "day")
    period_label = {
        "day": "день",
        "week": "неделя",
        "month": "месяц",
        "year": "год",
    }.get(period_value, period_value)
    if tracker.type == "count":
        mapping = load_count_xp_map(tracker)
        xp_line = f"XP правила: {format_count_xp_map(mapping)}" if mapping else "XP правила: нет"
    elif tracker.type == "scale":
        if tracker.xp_scale_min is not None and tracker.xp_scale_max is not None:
            xp_line = f"XP шкала: {tracker.xp_scale_min}–{tracker.xp_scale_max}"
        else:
            xp_line = "XP шкала: нет"
    else:
        xp_line = f"{xp_label}: {tracker.xp}"
    return (
        f"✏️ Редактирование трекера\n"
        f"Имя: {tracker.name}\n"
        f"Тип: {tracker_type_label(tracker.type)}\n"
        f"{xp_line}\n"
        f"Стрик: {streak_status}, {mode_label}, {period_label}"
    )


def tracker_streak_text(tracker: Tracker) -> str:
    enabled = True if tracker.streak_enabled is None else tracker.streak_enabled
    status = "включен" if enabled else "выключен"
    mode = tracker.streak_mode or "activity"
    mode_label = "по отметкам" if mode == "activity" else "по цели"
    period_value = tracker.streak_period or ("week" if mode == "goal" else "day")
    period_label = {
        "day": "день",
        "week": "неделя",
        "month": "месяц",
        "year": "год",
    }.get(period_value, period_value)
    lines = [
        "❤️‍🔥 Настройки стрика",
        f"Статус: {status}",
        f"Режим: {mode_label}",
        f"Период: {period_label}",
    ]
    if mode == "activity":
        if tracker.type == "binary":
            partial_ok = True if tracker.streak_partial_ok is None else tracker.streak_partial_ok
            lines.append(f"Частично: {'да' if partial_ok else 'нет'}")
        else:
            lines.append(f"Минимум: {tracker.streak_min_value or 0}")
    lines.append(f"Текущий стрик: {tracker_streak_value(tracker, today_iso())}")
    return "\n".join(lines)


# ----------------------------
# States
# ----------------------------
class MissionStates(StatesGroup):
    text = State()
    done_def = State()
    when_do = State()


class TrackerStates(StatesGroup):
    name = State()
    type = State()
    xp = State()
    xp_count_map = State()
    xp_scale_min = State()
    xp_scale_max = State()
    target = State()
    custom_value = State()
    comment = State()
    goal_value = State()
    edit_name = State()
    edit_xp = State()
    edit_xp_count_map = State()
    edit_xp_scale_min = State()
    edit_xp_scale_max = State()
    edit_streak_min = State()
    select_date = State()
    retro_day = State()


class JournalStates(StatesGroup):
    collecting = State()


class SettingsStates(StatesGroup):
    timezone = State()
    morning_time = State()
    evening_time = State()
    coach_prompt = State()
    weekly_review_time = State()
    google_oauth = State()


class CheckinStates(StatesGroup):
    morning_mission = State()


class CoachStates(StatesGroup):
    chat = State()


# ----------------------------
# Bot logic
# ----------------------------
class ActivityStreakMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        from_user = getattr(event, "from_user", None)
        if from_user:
            get_or_create_user(from_user.id, touch_streak=True, tg_user=from_user)
        return await handler(event, data)


router = Router()
router.message.middleware(ActivityStreakMiddleware())
router.callback_query.middleware(ActivityStreakMiddleware())
# user_tg_id -> (chat_id, message_id)
today_messages: dict[int, tuple[int, int]] = {}
retro_messages: dict[int, tuple[int, int, dt.date]] = {}
_evening_checkin_sent_at: dict[int, dt.datetime] = {}
_journal_ack_tasks: dict[int, asyncio.Task] = {}


def _should_trigger_diary_after_mission(user_id: int) -> bool:
    sent_at = _evening_checkin_sent_at.get(user_id)
    if not sent_at:
        return False
    if _utcnow() - sent_at > EVENING_DIARY_TRIGGER_WINDOW:
        _evening_checkin_sent_at.pop(user_id, None)
        return False
    return True


def _tracker_button_label(tracker: Tracker, date: dt.date) -> tuple[str, bool]:
    total, partial = tracker_progress(tracker.id, date)
    done_today = total > 0 or partial
    text = tracker_display_label(tracker, date)
    if not text:
        if tracker.type == "binary":
            marker = "✅" if done_today else "☑️"
            text = f"{marker} {tracker.name} (XP {tracker.xp})"
        elif tracker.type in {"time", "count"}:
            unit = tracker.unit or ""
            text = f"{tracker.name}: {int(total)}/{tracker.target}{unit}"
        else:
            text = f"{tracker.name}: {total or '—'}/10"
    text = f"{text}{tracker_streak_suffix(tracker, date)}"
    if done_today and not text.lstrip().startswith("✅"):
        text = f"✅ {text}"
    return text, done_today


def render_today_view(user_tg_id: int) -> tuple[str, InlineKeyboardMarkup]:
    user_row = get_or_create_user(user_tg_id)
    mission = get_mission(user_row.id)
    trackers = list_trackers(user_row.id)
    date = today_iso(user_row.tz)
    mission_text = mission.text or "(не задана)"
    status_label = {
        "not_set": "не задана",
        "set": "в процессе",
        "done": "✅ сделано",
        "partial": "↩️ частично",
        "fail": "❌ не сделано",
    }.get(mission.status, mission.status)

    lines = [
        f"🏠 Сегодня",
        f"Уровень {user_row.level}, XP {user_row.xp}/{xp_needed(user_row.level)}",
        f"🔥 Streak: {user_row.streak}",
        f"🎯 Миссия: {mission_text} | {status_label}",
    ]

    kb_rows: list[list[InlineKeyboardButton]] = []
    # Миссия
    if mission.status == "not_set":
        kb_rows.append([InlineKeyboardButton(text="🎯 Задать миссию", callback_data="mission:set")])
    elif mission.status == "set":
        kb_rows.append(
            [
                InlineKeyboardButton(text="✅", callback_data="mission:done"),
                InlineKeyboardButton(text="↩️", callback_data="mission:partial"),
                InlineKeyboardButton(text="❌", callback_data="mission:fail"),
                InlineKeyboardButton(text="✏️", callback_data="mission:set"),
            ]
        )

    # Трекеры как кнопки
    for t in trackers:
        text, _ = _tracker_button_label(t, date)
        kb_rows.append([InlineKeyboardButton(text=text, callback_data=f"tracker:tap:{t.id}")])

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    return "\n".join(lines), kb


def render_retro_view(user: User, date: dt.date) -> tuple[str, InlineKeyboardMarkup]:
    trackers = list_trackers(user.id)
    date_label = date.strftime("%d.%m.%Y")
    lines = [f"🕓 Заполнение: {date_label}"]
    kb_rows: list[list[InlineKeyboardButton]] = []
    if not trackers:
        kb_rows.append([InlineKeyboardButton(text="➕ Добавить трекер", callback_data="tracker:add_new")])
    else:
        for t in trackers:
            text, _ = _tracker_button_label(t, date)
            kb_rows.append([InlineKeyboardButton(text=text, callback_data=f"tracker:tap:{t.id}")])
    kb_rows.append([InlineKeyboardButton(text="📅 Другой день", callback_data="tracker:retro_menu")])
    kb_rows.append([InlineKeyboardButton(text="⬅️ Трекеры", callback_data="tracker:retro_exit")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    return "\n".join(lines), kb


def onboarding_next_kb(step: int, label: str = "Далее") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"onboarding:next:{step}")]
        ]
    )


def onboarding_goal_period_kb(tracker_id: int) -> InlineKeyboardMarkup:
    tracker = get_tracker(tracker_id)
    if tracker and tracker.type == "scale":
        week_label = "Неделя (ср. 1–10)"
        month_label = "Месяц (ср. 1–10)"
        year_label = "Год (ср. 1–10)"
    else:
        week_label = "Неделя"
        month_label = "Месяц"
        year_label = "Год"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=week_label, callback_data=f"onboarding:goal:week:{tracker_id}"),
                InlineKeyboardButton(text=month_label, callback_data=f"onboarding:goal:month:{tracker_id}"),
                InlineKeyboardButton(text=year_label, callback_data=f"onboarding:goal:year:{tracker_id}"),
            ]
        ]
    )


def onboarding_finish_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="В меню", callback_data="onboarding:finish")]
        ]
    )


async def send_onboarding_video(
    message: Message,
    step: int,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    filename = ONBOARDING_VIDEO_MAP.get(step)
    if not filename:
        raise ValueError(f"Unknown onboarding video for step {step}")
    video_path = os.path.join(ONBOARDING_VIDEO_DIR, filename)
    if not os.path.exists(video_path):
        await message.answer(
            "Видео онбординга временно недоступно.",
            reply_markup=reply_markup,
        )
        return
    await message.answer_video(
        FSInputFile(video_path),
        reply_markup=reply_markup,
    )


async def send_onboarding_step(message: Message, state: FSMContext, step: int) -> None:
    await state.update_data(onboarding=True)
    if step == 1:
        await send_onboarding_video(message, 1, onboarding_next_kb(2))
        return
    if step == 2:
        await send_onboarding_video(message, 2, onboarding_next_kb(3))
        return
    if step == 3:
        await send_onboarding_video(message, 3, onboarding_next_kb(4))
        return
    if step == 4:
        await send_onboarding_video(message, 4, onboarding_next_kb(5))
        return
    if step == 5:
        await send_onboarding_video(message, 5, onboarding_next_kb(6))
        return
    if step == 6:
        await send_onboarding_video(message, 6, onboarding_next_kb(7, label="Начать"))
        return
    if step == 7:
        await state.set_state(SettingsStates.timezone)
        await state.update_data(onboarding_step="timezone")
        await message.answer(
            "Чтобы даты, привычки и отчёты совпадали — настроим часовой пояс.\n"
            "Напиши текущее время у тебя сейчас (HH:MM).",
            reply_markup=main_reply_kb(message.from_user.id),
        )
        return
    if step == 8:
        await state.set_state(SettingsStates.morning_time)
        await state.update_data(onboarding_step="morning")
        await message.answer(
            "Утром я буду спрашивать главную цель дня.\n"
            "Во сколько ты обычно начинаешь день? Укажи время (09:30)."
        )
        return
    if step == 9:
        await state.set_state(SettingsStates.evening_time)
        await state.update_data(onboarding_step="evening")
        await message.answer(
            "Вечером — 1 минута на итоги дня (можно голосом).\n"
            "Во сколько ты обычно заканчиваешь день? Укажи время (23:00)."
        )
        return
    if step == 10:
        await state.set_state(TrackerStates.name)
        await state.update_data(onboarding_step="tracker_name", onboarding=True)
        await message.answer("Давай добавим первую привычку. Как назовём трекер?")
        return
    if step == 13:
        user = get_or_create_user(message.from_user.id)
        await state.set_state(SettingsStates.google_oauth)
        try:
            auth_url = _prepare_google_oauth_url(user.id)
            kb = _google_oauth_kb(
                auth_url,
                extra_rows=[[InlineKeyboardButton(text="Позже", callback_data="onboarding:next:14")]],
            )
            await message.answer(
                "Хочешь таблицу в Google Sheets? Там будет весь трекинг и дневник — твой личный архив.",
                reply_markup=kb,
            )
        except RuntimeError as exc:
            await message.answer(str(exc), reply_markup=onboarding_next_kb(14))
        return
    if step == 14:
        await state.clear()
        await message.answer(
            "Готово. Внизу меню: Сегодня, Трекеры, Дневник и Настройки.",
            reply_markup=onboarding_finish_kb(),
        )
        return


def today_inline_kb(user_tg_id: int) -> InlineKeyboardMarkup:
    _, kb = render_today_view(user_tg_id)
    return kb


def evening_checkin_text(user_id: int) -> str:
    mission = get_mission(user_id)
    mission_text = mission.text or "(не задана)"
    status_label = {
        "not_set": "не задана",
        "set": "в процессе",
        "done": "✅ сделано",
        "partial": "↩️ частично",
        "fail": "❌ не сделано",
    }.get(mission.status, mission.status)
    return (
        "🌙 Вечерний чек-ин\n"
        "Удалось выполнить миссию?\n"
        f"🎯 Миссия: {mission_text} | {status_label}"
    )


async def maybe_start_diary_after_mission(
    user: User, state: FSMContext, bot: Bot, chat_id: int
) -> None:
    if not _should_trigger_diary_after_mission(user.id):
        return
    _evening_checkin_sent_at.pop(user.id, None)
    current_state = await state.get_state()
    if current_state == JournalStates.collecting.state:
        return
    await start_journal_prompt(bot, chat_id, user, state)


async def refresh_today_view(user_tg_id: int, bot: Bot, chat_id: Optional[int] = None, force_new: bool = False):
    text, kb = render_today_view(user_tg_id)
    stored = today_messages.get(user_tg_id)
    if stored and not force_new:
        chat, msg = stored
        try:
            await bot.edit_message_text(chat_id=chat, message_id=msg, text=text, reply_markup=kb)
            return
        except Exception:
            pass
    target_chat = chat_id or (stored[0] if stored else None)
    if target_chat is None:
        return
    sent = await bot.send_message(target_chat, text, reply_markup=kb)
    today_messages[user_tg_id] = (sent.chat.id, sent.message_id)


async def refresh_retro_view(
    user_tg_id: int,
    date: dt.date,
    bot: Bot,
    chat_id: Optional[int] = None,
    force_new: bool = False,
) -> None:
    user = get_or_create_user(user_tg_id)
    text, kb = render_retro_view(user, date)
    stored = retro_messages.get(user_tg_id)
    if stored and stored[2] == date and not force_new:
        chat, msg, _ = stored
        try:
            await bot.edit_message_text(chat_id=chat, message_id=msg, text=text, reply_markup=kb)
            return
        except Exception:
            pass
    target_chat = chat_id or (stored[0] if stored else None)
    if target_chat is None:
        return
    sent = await bot.send_message(target_chat, text, reply_markup=kb)
    retro_messages[user_tg_id] = (sent.chat.id, sent.message_id, date)


async def send_today(message: Message, user_row: User) -> None:
    if user_row.tg_id in today_messages:
        await refresh_today_view(user_row.tg_id, message.bot, chat_id=message.chat.id)
    else:
        text, kb = render_today_view(user_row.tg_id)
        sent = await message.answer(text, reply_markup=kb)
        today_messages[user_row.tg_id] = (sent.chat.id, sent.message_id)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    await state.clear()
    if not user.onboarding_done:
        await send_onboarding_step(message, state, 1)
        return
    await send_today(message, user)
    await message.answer("Меню обновлено ✅", reply_markup=main_reply_kb(message.from_user.id))


@router.message(F.text == "🏠 Сегодня")
async def on_today(message: Message, state: FSMContext) -> None:
    await state.clear()
    await refresh_today_view(
        message.from_user.id,
        message.bot,
        chat_id=message.chat.id,
        force_new=True,
    )
    await message.answer("Меню обновлено ✅", reply_markup=main_reply_kb(message.from_user.id))


@router.message(F.text == "Настройки трекеров")
async def on_trackers(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    trackers = list_trackers(user.id)
    await state.clear()
    if not trackers:
        await message.answer(
            "Трекеров пока нет. Добавим?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="tracker:add_new")]]
            ),
        )
        return
    await message.answer(
        "Мои трекеры:",
        reply_markup=tracker_list_inline(trackers),
    )


@router.message(F.text == "🗒 Дневник")
async def on_journal(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    await state.clear()
    today = today_iso(user.tz)
    entry = get_journal_entry(user.id, today)
    recent_entries = list_journal_entries(user.id, JOURNAL_PAGE_SIZE)
    await message.answer(
        journal_menu_text(user, entry),
        reply_markup=journal_menu_inline(recent_entries),
    )


@router.message(F.text == "👤 Профиль")
async def on_profile(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    await state.clear()
    need = xp_needed(user.level)
    lines = [
        "👤 Профиль",
        f"Уровень: {user.level}",
        f"XP: {user.xp}/{need}",
        f"🔥 Streak: {user.streak}",
        f"Часовой пояс: {user.tz}",
    ]
    await message.answer("\n".join(lines), reply_markup=main_reply_kb(message.from_user.id))


@router.message(F.text == "🏆 Лидерборд")
async def on_leaderboard(message: Message, state: FSMContext) -> None:
    await state.clear()
    users = list_leaderboard_users()
    if not users:
        await message.answer("Пока нет участников.", reply_markup=main_reply_kb(message.from_user.id))
        return
    lines = ["🏆 Лидерборд"]
    for idx, user in enumerate(users, 1):
        name = leaderboard_display_name(user)
        lines.append(f"{idx}. {name} — lvl {user.level} — {user.xp} XP")
    await message.answer("\n".join(lines), reply_markup=main_reply_kb(message.from_user.id))


@router.message(F.text == "⚙️ Настройки")
async def on_settings(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    await state.clear()
    await message.answer(settings_text(user), reply_markup=settings_inline())


@router.callback_query(F.data == "settings:morning")
async def settings_morning(query, state: FSMContext) -> None:
    await state.set_state(SettingsStates.morning_time)
    await query.message.answer(
        "Во сколько присылать утреннее сообщение? (HH:MM, например 08:30)\n"
        "Чтобы отключить — напиши 'нет'."
    )
    await query.answer()


@router.callback_query(F.data == "settings:evening")
async def settings_evening(query, state: FSMContext) -> None:
    await state.set_state(SettingsStates.evening_time)
    await query.message.answer(
        "Во сколько присылать вечернее сообщение? (HH:MM, например 21:30)\n"
        "Чтобы отключить — напиши 'нет'."
    )
    await query.answer()


@router.callback_query(F.data == "settings:google")
async def settings_google(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.set_state(SettingsStates.google_oauth)
    current = user.google_sheet_url or "не подключено"
    try:
        auth_url = _prepare_google_oauth_url(user.id)
    except RuntimeError as exc:
        await query.message.answer(str(exc))
        await query.answer()
        return
    kb = _google_oauth_kb(auth_url)
    await query.message.answer(
        "Открой ссылку, авторизуйся в Google и подтверди доступ.\n"
        f"Текущий: {current}\n"
        "Чтобы отвязать — напиши 'нет'.",
        reply_markup=kb,
    )
    await query.answer()


@router.callback_query(F.data == "settings:timezone")
async def settings_timezone(query, state: FSMContext) -> None:
    await state.set_state(SettingsStates.timezone)
    await query.message.answer("Укажи текущее время у тебя (HH:MM), чтобы выставить часовой пояс.")
    await query.answer()


@router.callback_query(F.data == "settings:coach")
async def settings_coach(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    await query.message.answer(coach_settings_text(user), reply_markup=coach_settings_inline())
    await query.answer()


@router.callback_query(F.data == "settings:coach_prompt")
async def settings_coach_prompt(query, state: FSMContext) -> None:
    await state.set_state(SettingsStates.coach_prompt)
    await query.message.answer("Введи новый промпт для ИИ коуча.")
    await query.answer()


@router.callback_query(F.data == "settings:weekly_time")
async def settings_weekly_time(query, state: FSMContext) -> None:
    await state.set_state(SettingsStates.weekly_review_time)
    await query.message.answer("Во сколько присылать недельный анализ? (HH:MM)")
    await query.answer()


@router.callback_query(F.data == "settings:back")
async def settings_back(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    await query.message.answer(settings_text(user), reply_markup=settings_inline())
    await query.answer()


# ----------------------------
# Onboarding callbacks
# ----------------------------
@router.callback_query(F.data.startswith("onboarding:"))
async def onboarding_cb(query, state: FSMContext) -> None:
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "next":
        try:
            step = int(parts[2])
        except (IndexError, ValueError):
            await query.answer()
            return
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await send_onboarding_step(query.message, state, step)
        await query.answer()
        return
    if action == "goal":
        period = parts[2] if len(parts) > 2 else None
        tracker_id = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        if not period or not tracker_id:
            await query.answer()
            return
        await state.update_data(goal_tracker_id=tracker_id, goal_period=period, onboarding=True)
        await state.set_state(TrackerStates.goal_value)
        tracker = get_tracker(tracker_id)
        if tracker:
            await query.message.answer(goal_value_prompt(tracker, period))
        else:
            await query.message.answer("Введи цель числом.")
        await query.answer()
        return
    if action == "finish":
        set_onboarding_done(query.from_user.id, True)
        await state.clear()
        user = get_or_create_user(query.from_user.id)
        await send_today(query.message, user)
        await query.message.answer("Меню обновлено ✅", reply_markup=main_reply_kb(query.from_user.id))
        await query.answer()
        return
    await query.answer()


# ----------------------------
# Mission callbacks
# ----------------------------
@router.callback_query(F.data.startswith("mission:"))
async def mission_cb(query, state: FSMContext):
    user = get_or_create_user(query.from_user.id)
    action = query.data.split(":")[1]
    mission = get_mission(user.id)
    if action == "set":
        await state.set_state(MissionStates.text)
        await query.message.answer("Напиши текст миссии (1 строка).")
    elif action == "done":
        if mission and mission.status in {"done", "partial", "fail"}:
            await query.answer("Миссия уже отмечена.", show_alert=False)
            await refresh_today_view(query.from_user.id, query.message.bot)
            return
        update_mission(user.id, status="done")
        lvl, xp, up = add_xp(user.id, 10)
        txt = "Миссия отмечена как ✅ (+10 XP)"
        if up:
            txt += f"\n🎉 Новый уровень: {lvl}"
        await query.answer(txt, show_alert=False)
        await refresh_today_view(query.from_user.id, query.message.bot)
        await maybe_start_diary_after_mission(user, state, query.message.bot, query.message.chat.id)
    elif action == "partial":
        if mission and mission.status in {"done", "partial", "fail"}:
            await query.answer("Миссия уже отмечена.", show_alert=False)
            await refresh_today_view(query.from_user.id, query.message.bot)
            return
        update_mission(user.id, status="partial")
        lvl, xp, up = add_xp(user.id, 5)
        txt = "Миссия отмечена как ↩️ частично (+5 XP)"
        if up:
            txt += f"\n🎉 Новый уровень: {lvl}"
        await query.answer(txt, show_alert=False)
        await refresh_today_view(query.from_user.id, query.message.bot)
        await maybe_start_diary_after_mission(user, state, query.message.bot, query.message.chat.id)
    elif action == "fail":
        if mission and mission.status in {"done", "partial", "fail"}:
            await query.answer("Миссия уже отмечена.", show_alert=False)
            await refresh_today_view(query.from_user.id, query.message.bot)
            return
        update_mission(user.id, status="fail")
        await query.answer("Миссия отмечена как ❌", show_alert=False)
        await refresh_today_view(query.from_user.id, query.message.bot)
        await maybe_start_diary_after_mission(user, state, query.message.bot, query.message.chat.id)
    elif action == "done_def":
        await state.set_state(MissionStates.done_def)
        await query.message.answer("Напиши критерий done.")
    elif action == "when":
        await state.set_state(MissionStates.when_do)
        await query.message.answer("Когда планируешь делать миссию? (например 14:00–16:00)")
    await query.answer()


@router.message(MissionStates.text)
async def mission_set_text(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    text = message.text.strip()
    update_mission(user.id, text=text, status="set")
    await message.answer("Сохранил миссию.", reply_markup=main_reply_kb(message.from_user.id))
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(MissionStates.done_def)
async def mission_set_done_def(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    update_mission(user.id, done_def=message.text.strip())
    await message.answer(
        "Сохранил критерий done.", reply_markup=main_reply_kb(message.from_user.id)
    )
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(MissionStates.when_do)
async def mission_set_when(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    update_mission(user.id, when_do=message.text.strip())
    await message.answer(
        "Сохранил время для миссии.", reply_markup=main_reply_kb(message.from_user.id)
    )
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(SettingsStates.morning_time)
async def settings_set_morning_time(message: Message, state: FSMContext) -> None:
    parsed = parse_time_input(message.text)
    if parsed is None:
        await message.answer("Нужно время в формате HH:MM. Например 08:30.")
        return
    data = await state.get_data()
    if parsed == "" and data.get("onboarding_step") == "morning":
        await message.answer("Нужно время, а не 'нет'.")
        return
    user = get_or_create_user(message.from_user.id)
    update_user_reminders(user.id, morning_time=parsed)
    if data.get("onboarding_step") == "morning":
        await state.clear()
        await message.answer(
            f"Ок, утренний чек‑ин в {parsed}.",
            reply_markup=onboarding_next_kb(9),
        )
        return
    user = get_or_create_user(message.from_user.id)
    await message.answer(settings_text(user), reply_markup=settings_inline())
    await state.clear()


@router.message(SettingsStates.evening_time)
async def settings_set_evening_time(message: Message, state: FSMContext) -> None:
    parsed = parse_time_input(message.text)
    if parsed is None:
        await message.answer("Нужно время в формате HH:MM. Например 21:30.")
        return
    data = await state.get_data()
    if parsed == "" and data.get("onboarding_step") == "evening":
        await message.answer("Нужно время, а не 'нет'.")
        return
    user = get_or_create_user(message.from_user.id)
    update_user_reminders(user.id, evening_time=parsed)
    if data.get("onboarding_step") == "evening":
        await state.clear()
        await message.answer(
            f"Ок, вечерний чек‑ин в {parsed}.",
            reply_markup=onboarding_next_kb(10),
        )
        return
    user = get_or_create_user(message.from_user.id)
    await message.answer(settings_text(user), reply_markup=settings_inline())
    await state.clear()


@router.message(SettingsStates.timezone)
async def settings_set_timezone(message: Message, state: FSMContext) -> None:
    parsed = parse_time_input(message.text)
    if parsed is None:
        await message.answer("Нужно время в формате HH:MM. Например 21:30.")
        return
    if parsed == "":
        await message.answer("Нужно время, а не 'нет'.")
        return
    user = get_or_create_user(message.from_user.id)
    tz = _infer_tz_from_local_time(parsed)
    update_user_timezone(user.id, tz)
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    if data.get("onboarding_step") == "timezone":
        await state.clear()
        await message.answer(
            "Ок, часовой пояс настроен.",
            reply_markup=onboarding_next_kb(8),
        )
        return
    await message.answer(settings_text(user), reply_markup=settings_inline())
    await state.clear()


@router.message(SettingsStates.coach_prompt)
async def settings_set_coach_prompt(message: Message, state: FSMContext) -> None:
    prompt = message.text.strip()
    if not prompt:
        await message.answer("Промпт не может быть пустым.")
        return
    user = get_or_create_user(message.from_user.id)
    update_user_coach_prompt(user.id, prompt)
    user = get_or_create_user(message.from_user.id)
    await message.answer(coach_settings_text(user), reply_markup=coach_settings_inline())
    await state.clear()


@router.message(SettingsStates.weekly_review_time)
async def settings_set_weekly_time(message: Message, state: FSMContext) -> None:
    parsed = parse_time_input(message.text)
    if parsed is None:
        await message.answer("Нужно время в формате HH:MM. Например 10:00.")
        return
    user = get_or_create_user(message.from_user.id)
    update_user_weekly_review_time(user.id, parsed)
    user = get_or_create_user(message.from_user.id)
    await message.answer(coach_settings_text(user), reply_markup=coach_settings_inline())
    await state.clear()

@router.message(SettingsStates.google_oauth)
async def settings_set_google_oauth(message: Message, state: FSMContext) -> None:
    text = message.text.strip().lower()
    if text in {"нет", "no", "cancel", "отмена"}:
        user = get_or_create_user(message.from_user.id)
        clear_user_google_oauth(user.id)
        data = await state.get_data()
        if data.get("onboarding"):
            await state.clear()
            await message.answer("Ок, позже.", reply_markup=onboarding_next_kb(14))
            return
        await message.answer(settings_text(user), reply_markup=settings_inline())
        await state.clear()
        return
    user = get_or_create_user(message.from_user.id)
    try:
        auth_url = _prepare_google_oauth_url(user.id)
    except RuntimeError as exc:
        await message.answer(str(exc))
        await state.clear()
        return
    kb = _google_oauth_kb(auth_url)
    await message.answer("Ссылка для подключения:", reply_markup=kb)


@router.message(CheckinStates.morning_mission, ~F.text.startswith("/"))
async def checkin_morning_mission(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if not text:
        await message.answer("Напиши текст миссии (1 строка).")
        return
    user = get_or_create_user(message.from_user.id)
    update_mission(user.id, text=text, status="set")
    await message.answer(
        "Миссия на сегодня сохранена ✅", reply_markup=main_reply_kb(message.from_user.id)
    )
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


# ----------------------------
# Tracker callbacks
# ----------------------------
def tracker_goals_text(tracker: Tracker) -> str:
    goals = get_tracker_goals(tracker.id)
    unit = tracker.unit or ""
    def format_goal(key: str, label: str) -> str:
        value = goals.get(key)
        if value and value > 0:
            return f"{label}: {format_value(value)}{unit}"
        return f"{label}: нет"

    return (
        f"🎯 Цели трекера: {tracker.name}\n"
        f"{format_goal('week', 'Неделя')}\n"
        f"{format_goal('month', 'Месяц')}\n"
        f"{format_goal('year', 'Год')}"
    )


@router.callback_query(F.data.startswith("goal:"))
async def goal_cb(query, state: FSMContext):
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    tracker_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    period = parts[3] if len(parts) > 3 else None

    if action == "back":
        await refresh_today_view(query.from_user.id, query.message.bot)
        await query.answer()
        return

    if not tracker_id:
        await query.message.answer("Трекер не найден.")
        await query.answer()
        return

    tracker = get_tracker(tracker_id)
    if not tracker:
        await query.message.answer("Трекер не найден.")
        await query.answer()
        return

    if action == "open":
        await query.message.answer(
            tracker_goals_text(tracker),
            reply_markup=tracker_goals_inline(tracker.id),
        )
        await query.answer()
        return

    if action == "set" and period:
        await state.update_data(goal_tracker_id=tracker.id, goal_period=period)
        await state.set_state(TrackerStates.goal_value)
        await query.message.answer(
            goal_value_prompt(tracker, period)
        )
        await query.answer()
        return

    if action == "display":
        display = get_tracker_display(tracker.id)
        period_value = display.period if display else "week"
        format_value = display.format if display else "progress_goal"
        period_label = {"week": "Неделя", "month": "Месяц", "year": "Год"}.get(
            period_value, period_value
        )
        format_label = {
            "progress_goal": "Прогресс/цель",
            "progress": "Только прогресс",
            "goal": "Только цель",
            "percent": "Процент",
        }.get(format_value, format_value)
        text = (
            "Что показывать в кнопке?\n"
            f"Период: {period_label}\n"
            f"Формат: {format_label}"
        )
        await query.message.answer(
            text,
            reply_markup=tracker_display_inline(tracker.id, period_value, format_value),
        )
        await query.answer()
        return

    if action == "display_period" and period:
        display = get_tracker_display(tracker.id)
        format_value = display.format if display else "progress_goal"
        set_tracker_display(tracker.id, period, format_value)
        await query.message.answer(
            "Отображение обновлено ✅",
            reply_markup=tracker_display_inline(tracker.id, period, format_value),
        )
        await query.answer()
        return

    if action == "display_format" and period:
        display = get_tracker_display(tracker.id)
        period_value = display.period if display else "week"
        set_tracker_display(tracker.id, period_value, period)
        await query.message.answer(
            "Отображение обновлено ✅",
            reply_markup=tracker_display_inline(tracker.id, period_value, period),
        )
        await query.answer()
        return

    await query.answer()

def parse_tracker_payload(data: str) -> Tuple[str, Optional[int], Optional[str]]:
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    tracker_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if len(parts) > 3:
        extra = parts[3]
    elif len(parts) > 2 and tracker_id is None:
        extra = parts[2]
    else:
        extra = None
    return action, tracker_id, extra


@router.callback_query(F.data.startswith("tracker:"))
async def tracker_cb(query, state: FSMContext):
    user = get_or_create_user(query.from_user.id)
    action, tracker_id, extra = parse_tracker_payload(query.data)
    data = await state.get_data()
    retro_date = None
    retro_raw = data.get("retro_date")
    if retro_raw:
        try:
            retro_date = dt.date.fromisoformat(str(retro_raw))
        except ValueError:
            retro_date = None
    log_actions = {"tap", "toggle", "partial", "add", "custom"}
    date = retro_date if retro_date and action in log_actions else today_iso(user.tz)
    tracker = get_tracker(tracker_id) if tracker_id else None
    if tracker and tracker.user_id != user.id:
        tracker = None

    if action == "retro_menu":
        await state.set_state(TrackerStates.select_date)
        await query.message.answer(
            "Выбери день для заполнения:",
            reply_markup=retro_dates_inline(user.tz),
        )
        await query.answer()
        return

    if action == "retro_manual":
        await state.set_state(TrackerStates.select_date)
        await query.message.answer(
            "Введи дату (DD.MM или YYYY-MM-DD). Например: 03.02 или 2026-02-03."
        )
        await query.answer()
        return

    if action == "retro_date" and extra:
        selected = None
        try:
            selected = dt.date.fromisoformat(extra)
        except ValueError:
            selected = None
        if not selected:
            await query.message.answer("Не смог распознать дату. Попробуй ещё раз.")
            await query.answer()
            return
        if selected > today_iso(user.tz):
            await query.message.answer("Будущие даты пока нельзя заполнять.")
            await query.answer()
            return
        await state.update_data(retro_date=selected.isoformat())
        await state.set_state(TrackerStates.retro_day)
        await refresh_retro_view(query.from_user.id, selected, query.message.bot, chat_id=query.message.chat.id, force_new=True)
        await query.answer()
        return

    if action == "retro_exit":
        await state.clear()
        trackers = list_trackers(user.id)
        if not trackers:
            await query.message.answer(
                "Трекеров пока нет. Добавим?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="tracker:add_new")]]
                ),
            )
        else:
            await query.message.answer("Мои трекеры:", reply_markup=tracker_list_inline(trackers))
        await query.answer()
        return

    if action == "tap" and tracker:
        if tracker.type == "binary":
            total, _ = tracker_progress(tracker_id, date)
            if total == 0:
                log_tracker(tracker_id, date, 1)
                earned = tracker_xp_for_value(tracker, 1)
                lvl, xp, up = add_xp(user.id, earned)
                msg = f"{tracker.name}: ✅ (+{earned} XP)"
                if up:
                    msg += f"\n🎉 Новый уровень: {lvl}"
                await query.answer(msg, show_alert=False)
            else:
                clear_tracker_logs(tracker_id, date)
                await query.answer("Отмена отметки ↩️", show_alert=False)
            if retro_date:
                await refresh_retro_view(
                    query.from_user.id,
                    date,
                    query.message.bot,
                    chat_id=query.message.chat.id,
                    force_new=True,
                )
            else:
                await refresh_today_view(
                    query.from_user.id,
                    query.message.bot,
                    chat_id=query.message.chat.id,
                    force_new=True,
                )
        else:
            text, kb = tracker_input_prompt(tracker, date)
            await query.message.answer(text, reply_markup=kb)
            await query.answer()
    elif action == "toggle" and tracker_id:
        total, _ = tracker_progress(tracker_id, date)
        if total == 0:
            log_tracker(tracker_id, date, 1)
            earned = tracker_xp_for_value(tracker, 1) if tracker else 0
            lvl, xp, up = add_xp(user.id, earned)
            txt = f"Отмечено ✅ (+{earned} XP)"
            if up:
                txt += f"\n🎉 Новый уровень: {lvl}"
            await query.message.answer(txt)
        else:
            clear_tracker_logs(tracker_id, date)
            await query.message.answer("Отмена отметки ↩️")
        if retro_date:
            await refresh_retro_view(
                query.from_user.id,
                date,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
        else:
            await refresh_today_view(
                query.from_user.id,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
    elif action == "partial" and tracker_id:
        log_tracker(tracker_id, date, 0.5, partial=True)
        earned = tracker_xp_for_value(tracker, 1, partial=True) if tracker else 0
        lvl, xp, up = add_xp(user.id, earned)
        txt = f"Отмечено как частично ↩️ (+{earned} XP)"
        if up:
            txt += f"\n🎉 Новый уровень: {lvl}"
        await query.message.answer(txt)
        if retro_date:
            await refresh_retro_view(
                query.from_user.id,
                date,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
        else:
            await refresh_today_view(
                query.from_user.id,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
    elif action == "add" and tracker_id and extra:
        value = float(extra)
        log_tracker(tracker_id, date, value)
        earned = tracker_xp_for_value(tracker, value) if tracker else 0
        lvl, xp, up = add_xp(user.id, earned)
        txt = f"+{value} добавлено (+{earned} XP)"
        if up:
            txt += f"\n🎉 Новый уровень: {lvl}"
        await query.message.answer(txt)
        if retro_date:
            await refresh_retro_view(
                query.from_user.id,
                date,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
        else:
            await refresh_today_view(
                query.from_user.id,
                query.message.bot,
                chat_id=query.message.chat.id,
                force_new=True,
            )
    elif action == "custom" and tracker_id:
        await state.update_data(tracker_id=tracker_id)
        await state.set_state(TrackerStates.custom_value)
        await query.message.answer("Введи число для трекера.")
    elif action == "card" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await query.message.answer(
                tracker_card_text(tracker),
                reply_markup=tracker_card_inline(tracker.id),
            )
    elif action == "delete" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await query.message.answer(
                f"Удалить трекер «{tracker.name}»?",
                reply_markup=tracker_delete_confirm_inline(tracker.id),
            )
    elif action == "delete_confirm" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            set_tracker_active(tracker.id, False)
            await query.message.answer(
                "Трекер удален ✅", reply_markup=main_reply_kb(query.from_user.id)
            )
            await refresh_today_view(query.from_user.id, query.message.bot)
    elif action == "edit" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await query.message.answer(
                tracker_edit_text(tracker),
                reply_markup=tracker_edit_inline(tracker.id),
            )
    elif action == "edit_name" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await state.update_data(edit_tracker_id=tracker.id)
            await state.set_state(TrackerStates.edit_name)
            await query.message.answer(f"Новое имя (сейчас: {tracker.name})?")
    elif action == "edit_xp" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await state.update_data(edit_tracker_id=tracker.id)
            if tracker.type == "count":
                await state.set_state(TrackerStates.edit_xp_count_map)
                current = format_count_xp_map(load_count_xp_map(tracker)) or "нет"
                await query.message.answer(
                    f"Задай XP правила (например: 1-5 2-10 3-30). Сейчас: {current}"
                )
            elif tracker.type == "scale":
                await state.set_state(TrackerStates.edit_xp_scale_min)
                await query.message.answer(
                    f"Сколько XP за 1? (сейчас: {tracker.xp_scale_min})"
                )
            else:
                await state.set_state(TrackerStates.edit_xp)
                if tracker.type == "time":
                    await query.message.answer(
                        f"Сколько XP за 1 час? (сейчас: {tracker.xp})"
                    )
                else:
                    await query.message.answer(f"XP за выполнение? (сейчас: {tracker.xp})")
    elif action == "edit_type_menu" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await query.message.answer(
                "Выбери тип трекера:",
                reply_markup=tracker_edit_type_inline(tracker.id, tracker.type),
            )
    elif action == "edit_type" and tracker_id and extra:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            if extra not in {"binary", "time", "count", "scale"}:
                await query.message.answer("Неизвестный тип.")
                await query.answer()
                return
            update_tracker(tracker.id, type_=extra)
            tracker = get_tracker(tracker.id)
            if tracker:
                await query.message.answer(
                    tracker_edit_text(tracker),
                    reply_markup=tracker_edit_inline(tracker.id),
                )
    elif action == "streak" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await query.message.answer(
                tracker_streak_text(tracker),
                reply_markup=tracker_streak_inline(tracker),
            )
    elif action == "streak_toggle" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            enabled = True if tracker.streak_enabled is None else tracker.streak_enabled
            update_tracker_streak(tracker.id, enabled=not enabled)
            tracker = get_tracker(tracker.id)
            if tracker:
                await query.message.answer(
                    tracker_streak_text(tracker),
                    reply_markup=tracker_streak_inline(tracker),
                )
    elif action == "streak_mode" and tracker_id and extra:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            if extra not in {"activity", "goal"}:
                await query.message.answer("Неизвестный режим.")
                await query.answer()
                return
            period = tracker.streak_period
            if extra == "goal" and period not in {"week", "month", "year"}:
                period = "week"
            if extra == "activity" and period not in {"day", "week", "month"}:
                period = "day"
            update_tracker_streak(tracker.id, mode=extra, period=period)
            tracker = get_tracker(tracker.id)
            if tracker:
                await query.message.answer(
                    tracker_streak_text(tracker),
                    reply_markup=tracker_streak_inline(tracker),
                )
    elif action == "streak_period" and tracker_id and extra:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            update_tracker_streak(tracker.id, period=extra)
            tracker = get_tracker(tracker.id)
            if tracker:
                await query.message.answer(
                    tracker_streak_text(tracker),
                    reply_markup=tracker_streak_inline(tracker),
                )
    elif action == "streak_partial" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            partial_ok = True if tracker.streak_partial_ok is None else tracker.streak_partial_ok
            update_tracker_streak(tracker.id, partial_ok=not partial_ok)
            tracker = get_tracker(tracker.id)
            if tracker:
                await query.message.answer(
                    tracker_streak_text(tracker),
                    reply_markup=tracker_streak_inline(tracker),
                )
    elif action == "streak_min" and tracker_id:
        if not tracker:
            await query.message.answer("Трекер не найден.")
        else:
            await state.update_data(edit_tracker_id=tracker.id)
            await state.set_state(TrackerStates.edit_streak_min)
            await query.message.answer(
                f"Минимум для зачёта? (сейчас: {tracker.streak_min_value})"
            )
    elif action == "add_new":
        await state.set_state(TrackerStates.name)
        await query.message.answer("Имя трекера?")
    await query.answer()


@router.message(TrackerStates.select_date)
async def tracker_select_date(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Введи дату (DD.MM или YYYY-MM-DD).")
        return
    if raw.lower() in {"назад", "отмена", "cancel", "back"}:
        await state.clear()
        trackers = list_trackers(user.id)
        if not trackers:
            await message.answer(
                "Трекеров пока нет. Добавим?",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="tracker:add_new")]]
                ),
            )
        else:
            await message.answer("Мои трекеры:", reply_markup=tracker_list_inline(trackers))
        return
    selected = parse_date_input(raw, user.tz)
    if not selected:
        await message.answer("Не понял дату. Пример: 03.02 или 2026-02-03.")
        return
    if selected > today_iso(user.tz):
        await message.answer("Будущие даты пока нельзя заполнять.")
        return
    await state.update_data(retro_date=selected.isoformat())
    await state.set_state(TrackerStates.retro_day)
    await refresh_retro_view(message.from_user.id, selected, message.bot, chat_id=message.chat.id, force_new=True)


@router.message(TrackerStates.custom_value)
async def tracker_custom_value(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    tracker_id = data.get("tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        value = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число. Попробуй ещё раз.")
        return
    retro_date = None
    retro_raw = data.get("retro_date")
    if retro_raw:
        try:
            retro_date = dt.date.fromisoformat(str(retro_raw))
        except ValueError:
            retro_date = None
    target_date = retro_date or today_iso(user.tz)
    log_tracker(tracker_id, target_date, value)
    tracker = get_tracker(tracker_id)
    earned = tracker_xp_for_value(tracker, value) if tracker else 0
    lvl, xp, up = add_xp(user.id, earned)
    txt = f"+{value} добавлено (+{earned} XP)"
    if up:
        txt += f"\n🎉 Новый уровень: {lvl}"
    await message.answer(txt)
    if retro_date:
        await refresh_retro_view(
            message.from_user.id,
            target_date,
            message.bot,
            chat_id=message.chat.id,
            force_new=True,
        )
        await state.set_state(TrackerStates.retro_day)
        await state.update_data(tracker_id=None)
    else:
        await refresh_today_view(
            message.from_user.id,
            message.bot,
            chat_id=message.chat.id,
            force_new=True,
        )
        await state.clear()


@router.message(TrackerStates.edit_name)
async def tracker_edit_name(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    name = message.text.strip()
    if not name:
        await message.answer("Имя не может быть пустым.")
        return
    update_tracker(tracker_id, name=name)
    tracker = get_tracker(tracker_id)
    if tracker:
        await message.answer(
            tracker_edit_text(tracker),
            reply_markup=tracker_edit_inline(tracker.id),
        )
    else:
        await message.answer("Имя обновлено ✅")
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(TrackerStates.edit_xp)
async def tracker_edit_xp(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        xp = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 10.")
        return
    update_tracker(tracker_id, xp=xp)
    tracker = get_tracker(tracker_id)
    if tracker:
        await message.answer(
            tracker_edit_text(tracker),
            reply_markup=tracker_edit_inline(tracker.id),
        )
    else:
        await message.answer("XP обновлён ✅")
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(TrackerStates.edit_xp_count_map)
async def tracker_edit_xp_count_map(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    raw = message.text.strip()
    try:
        mapping = parse_count_xp_map(raw)
    except ValueError:
        await message.answer("Неверный формат. Пример: 1-5 2-10 3-30")
        return
    update_tracker_xp_rules(
        tracker_id,
        xp_count_map=json.dumps(mapping, ensure_ascii=False),
    )
    tracker = get_tracker(tracker_id)
    if tracker:
        await message.answer(
            tracker_edit_text(tracker),
            reply_markup=tracker_edit_inline(tracker.id),
        )
    else:
        await message.answer("XP правила обновлены ✅")
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(TrackerStates.edit_xp_scale_min)
async def tracker_edit_xp_scale_min(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        xp_min = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 1.")
        return
    await state.update_data(xp_scale_min=xp_min)
    await state.set_state(TrackerStates.edit_xp_scale_max)
    await message.answer("Сколько XP за оценку 10?")


@router.message(TrackerStates.edit_xp_scale_max)
async def tracker_edit_xp_scale_max(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    xp_min = data.get("xp_scale_min")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        xp_max = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 10.")
        return
    update_tracker_xp_rules(tracker_id, xp_scale_min=xp_min, xp_scale_max=xp_max)
    tracker = get_tracker(tracker_id)
    if tracker:
        await message.answer(
            tracker_edit_text(tracker),
            reply_markup=tracker_edit_inline(tracker.id),
        )
    else:
        await message.answer("XP шкалы обновлены ✅")
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(TrackerStates.edit_streak_min)
async def tracker_edit_streak_min(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("edit_tracker_id")
    if not tracker_id:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        value = float(message.text.strip().replace(",", "."))
    except ValueError:
        await message.answer("Нужно число. Например 1 или 0.5.")
        return
    update_tracker_streak(tracker_id, min_value=value)
    tracker = get_tracker(tracker_id)
    if tracker:
        await message.answer(
            tracker_streak_text(tracker),
            reply_markup=tracker_streak_inline(tracker),
        )
    await refresh_today_view(message.from_user.id, message.bot)
    await state.clear()


@router.message(TrackerStates.goal_value)
async def tracker_goal_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    tracker_id = data.get("goal_tracker_id")
    period = data.get("goal_period")
    if not tracker_id or not period:
        await message.answer("Трекер не найден.")
        await state.clear()
        return
    try:
        value = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число. Попробуй ещё раз.")
        return
    tracker = get_tracker(tracker_id)
    if tracker and tracker.type == "scale" and not (1 <= value <= 10):
        await message.answer("Для шкалы 1–10 нужно число от 1 до 10.")
        return
    set_tracker_goal(tracker_id, period, value)
    if data.get("onboarding"):
        text = "Цель сохранена ✅"
        if tracker:
            text = f"{text}\n\n{tracker_goals_text(tracker)}"
        await state.clear()
        set_onboarding_done(message.from_user.id, True)
        await message.answer(text, reply_markup=main_reply_kb(message.from_user.id))
        return
    if tracker:
        await message.answer(
            f"Цель сохранена ✅\n\n{tracker_goals_text(tracker)}",
            reply_markup=tracker_goals_inline(tracker_id),
        )
    else:
        await message.answer("Цель сохранена ✅")
    await state.clear()


# ----------------------------
# Tracker creation
# ----------------------------
@router.message(TrackerStates.name)
async def tracker_set_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    await state.update_data(name=name)
    await state.set_state(TrackerStates.type)
    await message.answer(
        "Выбери тип трекера:\n"
        "• <b>Бинарный</b> — сделал/не сделал (пример: медитация утром)\n"
        "• <b>Время</b> — сколько минут/часов (пример: время работы)\n"
        "• <b>Количество</b> — сколько раз/штук (пример: прочитанные страницы)\n"
        "• <b>Шкала 1–10</b> — субъективная оценка чего-либо (пример: мое настроение сегодня)\n\n"
        "Для привычек можно задать цели на неделю/месяц/год — цель всегда будет перед глазами.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Бинарный", callback_data="create:type:binary"),
                    InlineKeyboardButton(text="Время", callback_data="create:type:time"),
                ],
                [
                    InlineKeyboardButton(text="Количество", callback_data="create:type:count"),
                    InlineKeyboardButton(text="Шкала 1–10", callback_data="create:type:scale"),
                ],
            ]
        ),
    )


@router.callback_query(F.data.startswith("create:type:"))
async def tracker_set_type(query, state: FSMContext):
    type_ = query.data.split(":")[2]
    await state.update_data(type=type_)
    data = await state.get_data()
    xp_note = ""
    if data.get("onboarding"):
        xp_note = (
            "За выполненную привычку ты получаешь очки — XP. "
            "Ты сам решаешь, сколько: за лёгкую задачу можно поставить 1 XP, "
            "за сложную — 15.\n\n"
        )
    if type_ == "count":
        await state.set_state(TrackerStates.xp_count_map)
        await query.message.answer(
            f"{xp_note}Задай XP правила (пример: 1-5 2-10 3-30). "
            "Если значения нет в списке, XP будет 0."
        )
    elif type_ == "scale":
        await state.set_state(TrackerStates.xp_scale_min)
        await query.message.answer(f"{xp_note}Сколько XP за оценку 1?")
    else:
        await state.set_state(TrackerStates.xp)
        if type_ == "time":
            await query.message.answer(
                f"{xp_note}Сколько XP давать за 1 час? (число, например 2)"
            )
        else:
            await query.message.answer(f"{xp_note}XP за выполнение? (число, например 10)")
    await query.answer()


@router.message(TrackerStates.xp)
async def tracker_set_xp(message: Message, state: FSMContext) -> None:
    try:
        xp = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 10.")
        return
    await state.update_data(xp=xp)
    await finalize_tracker(message, state)


@router.message(TrackerStates.xp_count_map)
async def tracker_set_xp_count_map(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    try:
        mapping = parse_count_xp_map(raw)
    except ValueError:
        await message.answer("Неверный формат. Пример: 1-5 2-10 3-30")
        return
    await state.update_data(xp_count_map=json.dumps(mapping, ensure_ascii=False), xp=0)
    await finalize_tracker(message, state)


@router.message(TrackerStates.xp_scale_min)
async def tracker_set_xp_scale_min(message: Message, state: FSMContext) -> None:
    try:
        xp_min = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 1.")
        return
    await state.update_data(xp_scale_min=xp_min)
    await state.set_state(TrackerStates.xp_scale_max)
    await message.answer("Сколько XP за оценку 10?")


@router.message(TrackerStates.xp_scale_max)
async def tracker_set_xp_scale_max(message: Message, state: FSMContext) -> None:
    try:
        xp_max = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 10.")
        return
    await state.update_data(xp_scale_max=xp_max, xp=0)
    await finalize_tracker(message, state)


@router.message(TrackerStates.target)
async def tracker_set_target(message: Message, state: FSMContext) -> None:
    try:
        target = int(message.text.strip())
    except ValueError:
        await message.answer("Нужно число. Например 120.")
        return
    await state.update_data(target=target)
    await finalize_tracker(message, state)


async def finalize_tracker(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    unit = "ч" if data.get("type") == "time" else ""
    tracker_id = add_tracker(
        user_id=user.id,
        name=data["name"],
        type_=data["type"],
        xp=data.get("xp", 10),
        target=data.get("target", 0),
        unit=unit,
        xp_count_map=data.get("xp_count_map"),
        xp_scale_min=data.get("xp_scale_min"),
        xp_scale_max=data.get("xp_scale_max"),
    )
    if data.get("onboarding"):
        await message.answer("Трекер создан ✅")
        await message.answer(
            "Теперь поставим цель, чтобы она была перед глазами. На какой период?",
            reply_markup=onboarding_goal_period_kb(tracker_id),
        )
        await state.clear()
        return
    await message.answer("Трекер создан ✅", reply_markup=main_reply_kb(message.from_user.id))
    await state.clear()


# ----------------------------
# Journal
# ----------------------------
async def start_journal_prompt(bot: Bot, chat_id: int, user: User, state: FSMContext) -> int:
    entry = start_journal_entry(user.id, today_iso(user.tz))
    await state.set_state(JournalStates.collecting)
    await state.update_data(
        journal_entry_id=entry.id,
        journal_pending_count=0,
        journal_transcript_failed=False,
    )
    cancel_journal_ack(chat_id)
    await bot.send_message(chat_id, DEFAULT_JOURNAL_PROMPT, reply_markup=journal_collect_inline())
    return entry.id


@router.callback_query(F.data == "journal:menu")
async def journal_menu(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    cancel_journal_ack(query.message.chat.id)
    await state.clear()
    entry = get_journal_entry(user.id, today_iso(user.tz))
    recent_entries = list_journal_entries(user.id, JOURNAL_PAGE_SIZE)
    await query.message.answer(
        journal_menu_text(user, entry), reply_markup=journal_menu_inline(recent_entries)
    )
    await query.answer()


@router.callback_query(F.data == "journal:start")
async def journal_start(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await start_journal_prompt(query.message.bot, query.message.chat.id, user, state)
    await query.answer()


@router.callback_query(F.data == "journal:finish")
async def journal_finish(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    cancel_journal_ack(query.message.chat.id)
    data = await state.get_data()
    entry_id = data.get("journal_entry_id")
    if not entry_id:
        entry = get_journal_entry(user.id, today_iso(user.tz))
        entry_id = entry.id if entry else None
    if not entry_id:
        await query.message.answer("Нет активной заметки.")
        await query.answer()
        return
    close_journal_entry(entry_id, auto_closed=False)
    await state.clear()
    await query.message.answer(
        "Заметка сохранена ✅", reply_markup=main_reply_kb(query.from_user.id)
    )
    await query.answer()


@router.callback_query(F.data == "journal:clear_today")
async def journal_clear_today(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    cancel_journal_ack(query.message.chat.id)
    clear_journal_entry(user.id, today_iso(user.tz))
    await state.clear()
    await query.message.answer("Заметка очищена.")
    await query.answer()


@router.callback_query(F.data.startswith("journal:list:"))
async def journal_list(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    try:
        offset = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        offset = 0
    total = count_journal_entries(user.id)
    entries = list_journal_entries(user.id, JOURNAL_PAGE_SIZE, offset)
    if not entries:
        await query.message.answer("Пока нет заметок.")
        await query.answer()
        return
    await query.message.answer(
        "📚 История дневника:", reply_markup=journal_entries_inline(entries, offset, total)
    )
    await query.answer()


@router.callback_query(F.data.startswith("journal:view:"))
async def journal_view(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    parts = query.data.split(":")
    entry_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if not entry_id:
        await query.message.answer("Заметка не найдена.")
        await query.answer()
        return
    with db_session() as session:
        entry = session.get(JournalEntry, entry_id)
        if not entry or entry.user_id != user.id:
            entry = None
    if not entry:
        await query.message.answer("Заметка не найдена.")
        await query.answer()
        return
    date_label = entry.date.strftime("%d.%m.%Y")
    text = _truncate_for_tg(entry.text or "(пусто)")
    status = "открыта" if entry.status == "open" else "закрыта"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✍️ Дополнить", callback_data="journal:start"),
                InlineKeyboardButton(text="⬅️ Меню", callback_data="journal:menu"),
            ]
        ]
    )
    await query.message.answer(
        f"🗒 Заметка {date_label} ({status})\n\n{text}", reply_markup=kb
    )
    await query.answer()


@router.callback_query(F.data.startswith("journal:reports:"))
async def journal_reports(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    try:
        offset = int(query.data.split(":")[2])
    except (IndexError, ValueError):
        offset = 0
    total = count_weekly_reports(user.id)
    reports = list_weekly_reports(user.id, REPORT_PAGE_SIZE, offset)
    if not reports:
        await query.message.answer("Пока нет недельных отчетов.")
        await query.answer()
        return
    await query.message.answer(
        "🧠 Недельные отчеты:", reply_markup=journal_reports_inline(reports, offset, total)
    )
    await query.answer()


@router.callback_query(F.data.startswith("journal:report:"))
async def journal_report_view(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    await state.clear()
    parts = query.data.split(":")
    report_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    if not report_id:
        await query.message.answer("Отчет не найден.")
        await query.answer()
        return
    with db_session() as session:
        report = session.get(JournalWeeklyReport, report_id)
        if not report or report.user_id != user.id:
            report = None
    if not report:
        await query.message.answer("Отчет не найден.")
        await query.answer()
        return
    start = report.week_start.strftime("%d.%m.%Y")
    end = report.week_end.strftime("%d.%m.%Y")
    text = _truncate_for_tg(report.analysis_text or "(пусто)")
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Обсудить неделю", callback_data=f"coach:start:{report.id}")],
            [InlineKeyboardButton(text="⬅️ Отчеты", callback_data="journal:reports:0")],
        ]
    )
    await query.message.answer(
        f"🧠 Отчет за неделю {start}–{end}\n\n{text}", reply_markup=kb
    )
    await query.answer()


@router.message(JournalStates.collecting, F.text)
async def journal_collect_text(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        return
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    entry_id = data.get("journal_entry_id")
    if not entry_id:
        entry = start_journal_entry(user.id, today_iso(user.tz))
        entry_id = entry.id
        await state.update_data(journal_entry_id=entry_id)
    append_journal_message(
        entry_id,
        user.id,
        message_type="text",
        text=message.text.strip(),
    )
    await schedule_journal_ack(message.bot, message.chat.id, state)


@router.message(JournalStates.collecting, F.voice)
async def journal_collect_voice(message: Message, state: FSMContext) -> None:
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    entry_id = data.get("journal_entry_id")
    if not entry_id:
        entry = start_journal_entry(user.id, today_iso(user.tz))
        entry_id = entry.id
        await state.update_data(journal_entry_id=entry_id)
    transcript = await transcribe_voice_message(message)
    placeholder = None
    if not transcript:
        placeholder = "Голосовое сообщение (транскрипция недоступна)"
    append_journal_message(
        entry_id,
        user.id,
        message_type="voice",
        text=placeholder,
        transcript=transcript,
        tg_file_id=message.voice.file_id if message.voice else None,
        duration_sec=message.voice.duration if message.voice else None,
    )
    await schedule_journal_ack(
        message.bot,
        message.chat.id,
        state,
        transcript_failed=not transcript,
    )


@router.message(JournalStates.collecting)
async def journal_collect_other(message: Message, state: FSMContext) -> None:
    await message.answer("Можно отправлять только текст или голосовые сообщения.")


# ----------------------------
# Coach chat
# ----------------------------
@router.callback_query(F.data.startswith("coach:start:"))
async def coach_start(query, state: FSMContext) -> None:
    user = get_or_create_user(query.from_user.id)
    parts = query.data.split(":")
    report_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    await state.set_state(CoachStates.chat)
    await state.update_data(coach_report_id=report_id)
    await query.message.answer(
        "ИИ коуч подключен. Напиши свой вопрос или тезис.",
        reply_markup=coach_inline(),
    )
    await query.answer()


@router.callback_query(F.data == "coach:stop")
async def coach_stop(query, state: FSMContext) -> None:
    await state.clear()
    await query.message.answer(
        "Чат с коучем завершен.", reply_markup=main_reply_kb(query.from_user.id)
    )
    await query.answer()


@router.message(CoachStates.chat, F.text)
async def coach_chat(message: Message, state: FSMContext) -> None:
    if message.text.startswith("/"):
        return
    user = get_or_create_user(message.from_user.id)
    data = await state.get_data()
    report_id = data.get("coach_report_id")
    user_input = message.text.strip()
    if not user_input:
        await message.answer("Напиши текст сообщения.")
        return
    try:
        messages = build_coach_messages(user, user_input)
        response, _model = await llm_chat(messages, temperature=0.7, max_tokens=900)
    except Exception:
        await message.answer(
            "Не удалось получить ответ от ИИ коуча. Попробуй позже.",
            reply_markup=coach_inline(),
        )
        return
    save_coach_message(user.id, "user", user_input, report_id=report_id)
    save_coach_message(user.id, "assistant", response, report_id=report_id)
    await message.answer(response, reply_markup=coach_inline())


@router.message(CoachStates.chat)
async def coach_chat_other(message: Message, state: FSMContext) -> None:
    await message.answer("Можно отправлять только текстовые сообщения.")


# ----------------------------
# Reminders
# ----------------------------
async def reminders_loop(bot: Bot, dp: Dispatcher, bot_id: int) -> None:
    await asyncio.sleep(2)
    while True:
        now_utc = _utcnow()

        for user in list_reminder_users("morning"):
            offset = dt.timedelta(minutes=_tz_offset_minutes(user.tz))
            local_dt = now_utc + offset
            local_date = local_dt.date()
            local_time = local_dt.strftime("%H:%M")
            if user.morning_time != local_time:
                continue
            if user.morning_last_date == local_date:
                continue
            key = StorageKey(bot_id=bot_id, chat_id=user.tg_id, user_id=user.tg_id)
            current_state = await dp.storage.get_state(key=key)
            if current_state:
                continue
            try:
                await bot.send_message(
                    user.tg_id,
                    "☀️ Доброе утро! Какая у тебя сегодня миссия?",
                    reply_markup=main_reply_kb(user.tg_id),
                )
                await dp.storage.set_state(key=key, state=CheckinStates.morning_mission)
                mark_checkin_sent(user.id, "morning", local_date)
            except Exception:
                pass

        for user in list_reminder_users("evening"):
            offset = dt.timedelta(minutes=_tz_offset_minutes(user.tz))
            local_dt = now_utc + offset
            local_date = local_dt.date()
            local_time = local_dt.strftime("%H:%M")
            if user.evening_time != local_time:
                continue
            if user.evening_last_date == local_date:
                continue
            key = StorageKey(bot_id=bot_id, chat_id=user.tg_id, user_id=user.tg_id)
            current_state = await dp.storage.get_state(key=key)
            if current_state:
                continue
            try:
                await bot.send_message(
                    user.tg_id,
                    evening_checkin_text(user.id),
                    reply_markup=evening_checkin_inline(user.tg_id),
                )
                _evening_checkin_sent_at[user.id] = now_utc
                mark_checkin_sent(user.id, "evening", local_date)
            except Exception:
                pass

        await asyncio.sleep(30)


async def journal_autoclose_loop(bot: Bot, dp: Dispatcher, bot_id: int) -> None:
    await asyncio.sleep(5)
    while True:
        cutoff = _utcnow() - dt.timedelta(hours=1)
        stale_entries = list_stale_journal_entries(cutoff)
        for entry_id, _user_id, tg_id in stale_entries:
            close_journal_entry(entry_id, auto_closed=True)
            key = StorageKey(bot_id=bot_id, chat_id=tg_id, user_id=tg_id)
            try:
                await bot.send_message(
                    tg_id,
                    "⏳ Заметка сохранена (нет новых сообщений).",
                    reply_markup=main_reply_kb(tg_id),
                )
                await dp.storage.set_state(key=key, state=None)
                await dp.storage.set_data(key=key, data={})
            except Exception:
                pass
        await asyncio.sleep(30)


async def weekly_review_loop(bot: Bot, dp: Dispatcher, bot_id: int) -> None:
    await asyncio.sleep(7)
    while True:
        now_utc = _utcnow()
        for user in list_weekly_review_users():
            if not user.weekly_review_time:
                continue
            offset = dt.timedelta(minutes=_tz_offset_minutes(user.tz))
            local_dt = now_utc + offset
            local_date = local_dt.date()
            if local_dt.weekday() != 6:
                continue
            if user.weekly_review_time != local_dt.strftime("%H:%M"):
                continue
            if user.weekly_review_last_date == local_date:
                continue
            week_end = local_date
            week_start = week_end - dt.timedelta(days=6)
            try:
                report = await generate_weekly_report(user, week_start, week_end)
                if report:
                    await bot.send_message(
                        user.tg_id,
                        f"🧠 Недельный отчет {week_start.strftime('%d.%m')}–{week_end.strftime('%d.%m')}",
                        reply_markup=weekly_report_inline(report.id),
                    )
                else:
                    await bot.send_message(
                        user.tg_id,
                        "На этой неделе нет заметок для отчета.",
                        reply_markup=main_reply_kb(user.tg_id),
                    )
                mark_weekly_review_sent(user.id, local_date)
            except Exception:
                traceback.print_exc()
                try:
                    await bot.send_message(
                        user.tg_id,
                        "Не удалось сформировать недельный отчет. Попробуем позже.",
                        reply_markup=main_reply_kb(user.tg_id),
                    )
                except Exception:
                    pass
        await asyncio.sleep(30)


# ----------------------------
# Entrypoint
# ----------------------------
async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан. Укажи переменную окружения BOT_TOKEN.")
    init_db()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    me = await bot.get_me()
    bot_id = me.id
    global BOT_USERNAME
    BOT_USERNAME = me.username
    dp = Dispatcher()
    dp.include_router(router)
    await start_web_server(bot)
    asyncio.create_task(reminders_loop(bot, dp, bot_id))
    asyncio.create_task(journal_autoclose_loop(bot, dp, bot_id))
    asyncio.create_task(weekly_review_loop(bot, dp, bot_id))
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
