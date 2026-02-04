# Схема БД (PostgreSQL) — полная версия под все эпики

Документ фиксирует целевую модель данных, чтобы не терять контекст по структуре БД. Это каноничная схема для перехода с SQLite на Postgres.

## Покрытие эпиков
- A: профиль, аватар, уровни, XP.
- B: часовой пояс, напоминания, чек-ины.
- C: трекеры (бинарные/шкала/время/количество), расписания, лимиты.
- D: миссия дня, дневной цикл, статусы, done definition.
- E: геймификация, стрики, достижения, награды.
- F: дерево целей год→квартал→месяц→неделя→action, связи с трекерами/миссиями.
- G/H: недельные/месячные/квартальные/годовые планы и итоги.
- I: дневник (текст/голос), транскрипты.
- J: экспорт.
- K: счетчики с обнулением и нормы.
- L: адаптация при отставании.
- M: Mini App (через API).
- N: ИИ-анализ дневника и библиотека инсайтов.

## Конвенции
- PK: `uuid` (генерируем на стороне приложения), внешние ключи по `uuid`.
- Время: `timestamptz`, дневные сущности — `date`.
- Большие таблицы (логи/дневник) — партиции по месяцу.
- Переменные структуры — `jsonb` (payload/настройки/AI-результаты).
- Все таблицы имеют `created_at`, большинство — `updated_at`, `archived_at` при soft-delete.

## Ядро пользователей и настройки
`users`
- `id`, `tg_id` (unique), `created_at`, `tz`, `locale`
- `level`, `xp_in_level`, `streak_total`, `last_seen_at`
- `status` (active/blocked)

`user_profile`
- `user_id` (PK/FK), `display_name`, `bio`
- `avatar_current_id`, `onboarding_state`

`user_settings`
- `user_id` (PK/FK), `morning_checkin_time`, `evening_checkin_time`
- `notifications_enabled`, `quiet_hours` (jsonb), `preferred_units` (jsonb)

## Миссия дня и ежедневный цикл
`missions`
- `id`, `user_id`, `date` (unique per user/date)
- `text`, `status` (not_set/set/done/partial/fail)
- `done_def`, `when_do`, `note`, `source`

`daily_checkins`
- `id`, `user_id`, `date`, `kind` (morning/evening)
- `mood` (1–10), `text`, `voice_transcript`, `created_at`

`daily_summary`
- `id`, `user_id`, `date`
- `mission_status`, `trackers_done`, `xp_earned`, `summary_text`

## Трекеры, расписания, логи
`trackers`
- `id`, `user_id`, `name`
- `type` (binary/time/count/scale)
- `kind` (habit/metric/counter/avoid)
- `difficulty`, `xp_reward`
- `period_type` (day/week/month/custom)
- `reset_period` (none/month/quarter/year) для счетчиков
- `target_mode` (at_least/at_most), `target_value`, `unit`
- `is_active`, `sort_order`

`tracker_schedule`
- `id`, `tracker_id`
- `days_mask` (7 бит, Пн=1), `exceptions` (jsonb), `skip_until`

`tracker_targets`
- `id`, `tracker_id`
- `start_date`, `end_date`, `target_value`, `unit`

`tracker_logs`
- `id`, `tracker_id`, `occurred_at`, `date`
- `value` (numeric), `partial` (bool), `comment`, `source`

`tracker_daily`
- `id`, `tracker_id`, `date`
- `total_value`, `partial`, `completed`, `computed_at`

## Счетчики и нормы (если нужно отдельно от трекеров)
Если потребуются отдельные сущности, можно вынести:
`counters`, `counter_logs`, `counter_periods`, но базово это покрывается `trackers` с `reset_period`.

## Цели и связи
`goals`
- `id`, `user_id`, `parent_id`
- `level` (year/quarter/month/week/action)
- `title`, `description`, `start_date`, `end_date`
- `status` (active/on_hold/done/cancelled)
- `progress_target`, `progress_unit`, `success_criteria`

`goal_links`
- `id`, `goal_id`
- `tracker_id` (nullable), `mission_date` (nullable), `weight`

`goal_progress`
- `id`, `goal_id`, `date`
- `value`, `note`, `source`

## Планы и итоги по периодам
`periods`
- `id`, `user_id`, `kind` (week/month/quarter/year)
- `start_date`, `end_date`, `label`

`period_plans`
- `id`, `period_id`, `focus_text`, `created_at`

`period_plan_items`
- `id`, `plan_id`
- `item_kind` (goal/tracker/mission/custom)
- `ref_id` (nullable), `title`
- `target_value`, `unit`, `weight`

`period_reviews`
- `id`, `period_id`
- `summary_text`, `mood`, `ai_summary` (jsonb)
- `plan_vs_fact` (jsonb агрегаты)

## Дневник и медиа
`journal_entries`
- `id`, `user_id`, `date`
- `text`, `voice_transcript`, `mood`, `tags` (jsonb)

`journal_media`
- `id`, `entry_id`, `tg_file_id`, `media_type`, `duration_sec`

`journal_tags`
- `id`, `user_id`, `tag`

`journal_entry_tags`
- `entry_id`, `tag_id`

## ИИ-анализ и инсайты
`ai_jobs`
- `id`, `user_id`, `kind`, `payload` (jsonb)
- `status` (queued/running/done/failed), `result` (jsonb)

`journal_ai_reports`
- `id`, `user_id`, `period_id` (неделя/месяц)
- `themes`, `patterns`, `what_helps`, `what_blocks`, `experiments` (jsonb)

`insights`
- `id`, `user_id`, `title`, `text`, `source`, `created_at`

`insight_library`
- `id`, `user_id`, `insight_id`, `is_key_of_month`, `month`

## Геймификация
`xp_ledger`
- `id`, `user_id`, `delta`
- `source` (mission/tracker/review/bonus/insight)
- `reference` (jsonb), `level_before`, `level_after`

`streaks`
- `id`, `user_id`, `scope` (overall/mission/tracker:{id})
- `current_value`, `best_value`, `updated_at`, `broken_at`

`achievements`
- `id`, `code`, `title`, `description`, `rule` (jsonb)

`user_achievements`
- `id`, `user_id`, `achievement_id`, `earned_at`

`avatar_items`
- `id`, `type`, `name`, `meta` (jsonb), `unlock_rule` (jsonb)

`user_avatar_items`
- `id`, `user_id`, `avatar_item_id`, `earned_at`

## Напоминания и уведомления
`reminders`
- `id`, `user_id`, `kind`
- `time_local`, `days_mask`, `tz`, `payload` (jsonb)
- `active`, `last_sent_at`, `next_run_at`

`notification_outbox`
- `id`, `user_id`, `channel` (tg)
- `payload` (jsonb), `scheduled_at`, `sent_at`, `status`, `error`

## Адаптация при отставании
`adaptation_events`
- `id`, `user_id`, `detected_at`, `severity`
- `reason` (jsonb), `proposal` (jsonb)
- `user_decision`, `applied_at`

## Экспорт
`exports`
- `id`, `user_id`, `type`, `format`
- `filters` (jsonb), `status`
- `file_path_or_url`, `created_at`, `completed_at`

## Индексы (минимум)
- `missions (user_id, date)`
- `journal_entries (user_id, date)`
- `tracker_logs (tracker_id, date)`
- `tracker_daily (tracker_id, date)`
- `goals (user_id, level)`
- `periods (user_id, kind, start_date)`
- `reminders (next_run_at)`
- `notification_outbox (scheduled_at, status)`

## Комментарии по масштабу
- Логи и дневник — партиционировать по `date` (месяц).
- Частые чтения (экран «Сегодня») — брать из `tracker_daily`, `missions`, `journal_entries`.
- Все вычисления XP/стрик/итогов — через сервисы + запись в `xp_ledger` и `streaks`.
