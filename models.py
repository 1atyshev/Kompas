from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    first_name = Column(String(128), nullable=True)
    last_name = Column(String(128), nullable=True)
    username = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    tz = Column(String(64), server_default="UTC", nullable=False)
    level = Column(Integer, server_default="1", nullable=False)
    xp = Column(Integer, server_default="0", nullable=False)
    streak = Column(Integer, server_default="0", nullable=False)
    streak_last_date = Column(Date, nullable=True)
    morning_time = Column(String(5), nullable=True)
    evening_time = Column(String(5), nullable=True)
    morning_last_date = Column(Date, nullable=True)
    evening_last_date = Column(Date, nullable=True)
    google_email = Column(String(255), nullable=True)
    google_sheet_id = Column(String(128), nullable=True)
    google_sheet_url = Column(String(512), nullable=True)
    google_connected_at = Column(DateTime(timezone=True), nullable=True)
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expiry = Column(DateTime(timezone=True), nullable=True)
    google_oauth_state = Column(String(128), nullable=True)
    google_oauth_state_expires_at = Column(DateTime(timezone=True), nullable=True)
    weekly_review_time = Column(String(5), nullable=True)
    weekly_review_last_date = Column(Date, nullable=True)
    coach_prompt = Column(Text, nullable=True)
    onboarding_done = Column(Boolean, server_default="false", nullable=False)


class Mission(Base):
    __tablename__ = "missions"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_missions_user_date"),
        Index("idx_missions_user_date", "user_id", "date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    text = Column(Text, server_default="", nullable=False)
    status = Column(String(16), server_default="not_set", nullable=False)
    done_def = Column(Text, server_default="", nullable=False)
    when_do = Column(Text, server_default="", nullable=False)


class Tracker(Base):
    __tablename__ = "trackers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False)
    difficulty = Column(String(32), server_default="medium", nullable=False)
    xp = Column(Integer, server_default="10", nullable=False)
    period = Column(String(16), server_default="day", nullable=False)
    target = Column(Integer, server_default="0", nullable=False)
    unit = Column(String(32), server_default="", nullable=False)
    active = Column(Boolean, server_default="true", nullable=False)
    order_index = Column(Integer, server_default="0", nullable=False)
    days = Column(String(64), server_default="", nullable=False)
    streak_enabled = Column(Boolean, server_default="true", nullable=False)
    streak_mode = Column(String(16), server_default="activity", nullable=False)
    streak_period = Column(String(16), server_default="day", nullable=False)
    streak_min_value = Column(Float, server_default="0", nullable=False)
    streak_partial_ok = Column(Boolean, server_default="true", nullable=False)
    xp_count_map = Column(Text, nullable=True)
    xp_scale_min = Column(Integer, nullable=True)
    xp_scale_max = Column(Integer, nullable=True)


class TrackerLog(Base):
    __tablename__ = "tracker_logs"
    __table_args__ = (Index("idx_tracker_logs_tracker_date", "tracker_id", "date"),)

    id = Column(Integer, primary_key=True)
    tracker_id = Column(Integer, ForeignKey("trackers.id"), nullable=False)
    date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    partial = Column(Boolean, server_default="false", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_journal_user_date"),
        Index("idx_journal_user_date", "user_id", "date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False)
    text = Column(Text, server_default="", nullable=False)
    status = Column(String(16), server_default="closed", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_message_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    auto_closed = Column(Boolean, server_default="false", nullable=False)


class JournalMessage(Base):
    __tablename__ = "journal_messages"
    __table_args__ = (Index("idx_journal_messages_entry", "entry_id"),)

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    message_type = Column(String(16), nullable=False)  # text | voice
    text = Column(Text, nullable=True)
    transcript = Column(Text, nullable=True)
    tg_file_id = Column(String(255), nullable=True)
    duration_sec = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class JournalWeeklyReport(Base):
    __tablename__ = "journal_weekly_reports"
    __table_args__ = (
        UniqueConstraint("user_id", "week_start", name="uq_journal_week_user_start"),
        Index("idx_journal_week_user", "user_id", "week_start"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    week_start = Column(Date, nullable=False)
    week_end = Column(Date, nullable=False)
    analysis_text = Column(Text, server_default="", nullable=False)
    model = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class CoachMessage(Base):
    __tablename__ = "coach_messages"
    __table_args__ = (Index("idx_coach_messages_user", "user_id"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    report_id = Column(Integer, ForeignKey("journal_weekly_reports.id"), nullable=True)
    role = Column(String(16), nullable=False)  # system | user | assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class TrackerGoal(Base):
    __tablename__ = "tracker_goals"
    __table_args__ = (
        UniqueConstraint("tracker_id", "period", name="uq_tracker_goal"),
        Index("idx_tracker_goals_tracker", "tracker_id"),
    )

    id = Column(Integer, primary_key=True)
    tracker_id = Column(Integer, ForeignKey("trackers.id"), nullable=False)
    period = Column(String(16), nullable=False)  # week | month | year
    target = Column(Float, server_default="0", nullable=False)


class TrackerGoalDisplay(Base):
    __tablename__ = "tracker_goal_display"
    __table_args__ = (UniqueConstraint("tracker_id", name="uq_tracker_goal_display"),)

    id = Column(Integer, primary_key=True)
    tracker_id = Column(Integer, ForeignKey("trackers.id"), nullable=False)
    period = Column(String(16), server_default="week", nullable=False)
    format = Column(String(16), server_default="progress_goal", nullable=False)


class FranklinSettings(Base):
    __tablename__ = "franklin_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_franklin_settings_user"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    cycle_start_week = Column(Date, nullable=False)
    enabled = Column(Boolean, server_default="true", nullable=False)
    reminder_date = Column(Date, nullable=True)
    reminder_morning_time = Column(String(5), nullable=True)
    reminder_day_time = Column(String(5), nullable=True)
    reminder_evening_time = Column(String(5), nullable=True)
    reminder_morning_last_date = Column(Date, nullable=True)
    reminder_day_last_date = Column(Date, nullable=True)
    reminder_evening_last_date = Column(Date, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FranklinVirtue(Base):
    __tablename__ = "franklin_virtues"
    __table_args__ = (
        UniqueConstraint("user_id", "order", name="uq_franklin_virtues_user_order"),
        Index("idx_franklin_virtues_user_active", "user_id", "active"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, server_default="", nullable=False)
    active = Column(Boolean, server_default="true", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FranklinMark(Base):
    __tablename__ = "franklin_marks"
    __table_args__ = (
        UniqueConstraint("virtue_id", "date", name="uq_franklin_mark_virtue_date"),
        Index("idx_franklin_marks_user_date", "user_id", "date"),
        Index("idx_franklin_marks_virtue_date", "virtue_id", "date"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    virtue_id = Column(Integer, ForeignKey("franklin_virtues.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
