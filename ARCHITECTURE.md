# Архитектура бэкенда и модель данных

Документ описывает, как хранить данные и как будет устроен бэкенд: от текущего прототипа до перехода на полнофункциональную базу (PostgreSQL).

Подробная и каноничная схема БД для всех эпиков зафиксирована в `DATABASE_SCHEMA.md`. Здесь — обзорный слой и архитектурные решения.

## Этапы
- Прототип (сейчас): один процесс aiogram + SQLite (`bot.db`), минимум таблиц, всё в одном файле.
- Альфа: выносим слой данных в PostgreSQL, вводим миграции (Alembic), раскладываем код по слоям (transport → application → domain → infra), добавляем фоновые задачи.
- Дальше: HTTP API для Mini App/интеграций, отдельный воркер/крон для напоминаний и агрегаций, кэш (Redis) под частые чтения.

## Слои и сервисы
- Transport: Telegram (aiogram), позже — HTTP (FastAPI) для Mini App/экспорта.
- Application/use-cases: команды/хэндлеры, которые вызывают доменные сервисы (без SQL внутри хэндлеров).
- Domain services: `UserService`, `MissionService`, `TrackerService`, `GoalService`, `JournalService`, `ReminderService`, `XpService`, `ExportService`. Они инкапсулируют правила (XP, streak, расписания, связи целей).
- Infra: репозитории (SQLAlchemy), Postgres, Redis (кэш + rate limit + отложенные задачи), очередь задач/крон (apscheduler/RQ/Celery — выбрать позже).
- Observability: структурные логи + метрики (позже).

## Ключевые сущности и таблицы (целевой PostgreSQL)
*Типы: UUID как PK, `timestamptz` для времени, `date` для дневных сущностей. В примерах оставлены ключевые поля.*

- `users`: `id`, `tg_id` (unique), `created_at`, `tz`, `locale`, `level`, `xp_in_level`, `streak_total`, `last_seen_at`.
- `user_settings`: `user_id`, `morning_checkin_time`, `evening_checkin_time`, `notifications_enabled`, `quiet_hours`, `preferred_units` (JSONB).
- `missions`: `id`, `user_id`, `date`, `text`, `status` (`not_set/set/done/partial/fail`), `done_def`, `when_do`, `note`, `created_at`, `updated_at`, `source` (manual/ai/import).
- `trackers`: `id`, `user_id`, `name`, `type` (`binary/time/count/scale`), `difficulty`, `xp_reward`, `period` (`day/week/month`), `target_value`, `unit`, `schedule` (битмаск дней или JSONB `{"days":[1,2,3], "skip_until":null}`), `is_active`, `sort_order`, `created_at`, `archived_at`.
- `tracker_logs`: `id`, `tracker_id`, `occurred_at`, `date`, `value` (numeric), `partial` (bool), `comment`, `source`, `created_at`.
- `tracker_daily`: материализованный срез на день для быстрых чтений: `id`, `tracker_id`, `date`, `total_value`, `partial` (bool), `completed` (bool), `computed_at`. Обновляется триггером/воркером при новых логах.
- `journal_entries`: `id`, `user_id`, `date`, `text`, `transcript`, `ai_summary` (JSONB), `mood` (1–10), `tags` (ARRAY/JSONB), `updated_at`.
- `goals`: `id`, `user_id`, `parent_id` (self FK), `level` (`year/quarter/month/week/action`), `title`, `description`, `start_date`, `end_date`, `status` (`active/on_hold/done/cancelled`), `progress_target`, `progress_unit`, `success_criteria`, `created_at`, `updated_at`.
- `goal_links`: связь целей с трекерами/миссиями: `id`, `goal_id`, `tracker_id` (nullable), `mission_date` (nullable), `weight` (0–1).
- `reminders`: `id`, `user_id`, `kind` (`morning_mission`, `evening_review`, `tracker_nudge`, `goal_ping`, `journal`), `time_local`, `days_mask`, `tz`, `payload` (JSONB, например tracker_id), `active`, `last_sent_at`, `next_run_at`.
- `notifications_outbox`: `id`, `user_id`, `channel` (`tg`), `payload` (JSONB), `scheduled_at`, `sent_at`, `status`, `error`.
- `xp_ledger`: `id`, `user_id`, `delta`, `source` (`mission`, `tracker`, `review`, `import`, `bonus`), `reference` (FK id + type), `level_before`, `level_after`, `created_at`. Позволяет пересчитать уровень и строить историю.
- `streaks`: `id`, `user_id`, `scope` (`overall`, `tracker:{id}`, `mission`), `current_value`, `best_value`, `updated_at`, `broken_at`. Можно хранить денормализованно для быстрого доступа.
- `exports`: `id`, `user_id`, `type` (`journal`, `trackers`, `all`), `format` (`txt/md/csv/json`), `filters` (JSONB), `status`, `file_path/url`, `created_at`, `completed_at`.

Минимально нужные индексы: `missions(user_id, date)`, `tracker_logs(tracker_id, date)`, `tracker_daily(tracker_id, date)`, `journal_entries(user_id, date)`, `goals(user_id, level)`, `reminders(next_run_at)`.

## Логика хранения и расчётов
- **Дневные сущности** (`missions`, `journal_entries`, `tracker_daily`) нормализованы на `date`, чтобы быстро отдавать экран «Сегодня» и итоги.
- **Логи трекеров** — атомарные события; агрегация в `tracker_daily` и вычисление streak/XP происходят в сервисе/воркере, чтобы не дублировать логику в UI.
- **XP**: любые награды фиксируются в `xp_ledger`; уровень и остаток в уровне хранятся в `users`. Пересчёт уровня через функцию, как в прототипе, но без прямых апдейтов из хэндлеров — через `XpService`.
- **Streak**: для `overall` и отдельных трекеров считаем на стороне сервиса (по `tracker_daily.completed`/`missions.status`) и кешируем в `streaks`.
- **Расписания/дни недели**: `schedule.days_mask` (битмаск 7 бит, 1=понедельник). Для кастомных расписаний — JSONB с датами исключений.
- **Цели**: дерево в одной таблице `goals` (self-FK). `goal_links` связывают привычки/миссии с целями, что позволяет строить “план vs факт”.
- **Напоминания**: `reminders` описывают правило; воркер раскладывает его в `notifications_outbox` с `scheduled_at`, из которой отправитель читает и бьёт в Telegram.
- **Экспорт**: запрос записывается в `exports`, воркер готовит файл/ссылку, статус обновляется.

## Минимальные улучшения для текущего SQLite перед миграцией
- Добавить `created_at`/`updated_at` в таблицы для последующей миграции.
- Хранить `days` трекеров как битмаск или нормализовать в отдельную таблицу `tracker_schedule`.
- Завести простую `xp_ledger` и `streaks` даже в SQLite, чтобы не терять историю при переносе.
- Вытащить SQL из хэндлеров в отдельные функции/репозитории, чтобы сменить движок на Postgres без переписывания хэндлеров.

## Миграция на Postgres (план)
- Ввести ORM (SQLAlchemy) + Alembic и перенести текущие таблицы в модели/миграции.
- Написать одноразовый мигратор SQLite → Postgres (по таблицам `users`, `missions`, `trackers`, `tracker_logs`, `journal_entries`).
- Разделить процессы: `bot` (хэндлеры) + `worker` (напоминания, агрегации, экспорт). Общие модели/сервисы лежат в `core/`.
- Добавить env-конфиг: `DATABASE_URL`, `REDIS_URL`, `APP_ENV`.

## Каркас каталогов (предложение)
```
core/
  domain/ (бизнес-логика: xp, streak, цели, трекеры, миссии)
  services/ (MissionService, TrackerService, ...)
  models/ (ORM-модели)
  repositories/ (интерфейсы + реализация под Postgres)
  workers/ (reminder, aggregation, export)
transport/
  telegram/ (aiogram handlers)
  http/ (FastAPI, Mini App API)
infra/
  db.py, redis.py, scheduler.py
```
