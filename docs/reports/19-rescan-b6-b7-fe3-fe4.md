# 19. rescan: B6, B7, FE3, FE4

Задание — `prompts/19-rescan-b6-b7-fe3-fe4.md`. Ветка `mvp`, по коммиту на задачу. Push в `origin/mvp` — по просьбе пользователя, для деплоя в Railway.

## До начала

- `rescan_core/tests/conftest.py`: схема теста ставится командой `SET search_path` (`set_config`) при каждой выдаче соединения, с проверкой, что она применилась — пулер Supabase не передаёт параметр `options` (`d859f7a`). Затем один пул соединений на весь прогон и таблицы одним запросом: каждый запрос к Supabase во Франкфурте стоит около 0,5 с, соединение — около 8 с (`6590fdf`).
- Базовый прогон на SQLite: `rescan_core` — 206 прошли, 2 пропущены (гонки — только PostgreSQL); сервисы снимков, пути, клиники, медикаментов — 20, 12, 8, 10, OK; node-тесты пилота — 42 из 42; ruff, mypy (29 файлов), `alembic check` — чисто. PostgreSQL до ускорения `conftest.py` шёл около 26 тестов за 10 минут, зелёный.

## Что сделано

| Задача | Кто | Коммит в `mvp` |
|---|---|---|
| Дизайн: каркасы и тексты P4–P8 и ошибок, решения, токены меток | дизайнер (Claude) | `a16035e` |
| FE4: пересдача (P7), шаг после визита (P8), ошибки пациента | Codex-2 начал, доделал агент Claude (у Codex кончился лимит) | `53a53f0` |
| FE3: врачи (P4), заявка (P5), статус заявки (P6), маршруты и моки по контракту B6 | фронтенд (Claude) | `7dc5608` |
| B6: API пациента — ссылки (HMAC), сессия, согласие, выбор, врачи, форматы, заявка | бэкенд (Claude) | `7a92986` |
| B7: заявки в CRM — Битрикс24 и вебхук, повторы, уведомление администратору, статус обратно | Codex-1 начал, доделал агент Claude, две правки контракта — координатор | `3a9d3f0` |
| Приёмочные тесты B6 и B7, проверки страниц пилота P4–P8 | тестировщик (Claude) | `fbab0e6` |
| Приёмка: ревью вёрстки на 360, 390, 1280 и две правки | координатор | `23762ba` |
| Чистка: черновые скрипты, старые демо, контур обучения снимков | координатор, по просьбе пользователя | `ce55ef9` |

Ревью. B6 по плану ревьюит Codex, но у него кончился лимит; ревью сделал координатор: CRITICAL и HIGH нет. B7 — координатор: CRITICAL и HIGH нет; MEDIUM — блокировка строки очереди держится всё время HTTP-запроса к CRM, это записано в контракте.

Правки контракта B7 при слиянии (координатор, с тестами):

- Успешное уведомление администратору не переводит заявку в `sent`: она остаётся `new`, аудит `crm.notify_sent` с `reason`, очередь `notify` — `done`.
- Ошибки `/v1/crm/status` и ручной отметки — в формате B6 `{"detail": {"code", "message"}}`: `bad_signature`, `request_not_found`, `invalid_transition`, `invalid_input`.
- Переходы вперёд через шаг (`new`/`sent` → `booked`): конечны только `booked` и `cancelled`, как в задании. Строгая цепочка не давала администратору отметить «записан» заявку, которая после уведомления осталась `new`. Нашли приёмочные тесты.
- Захват очереди CRM без сравнения времени в объектах сессии: на SQLite `deliver_pending` падал на втором проходе (наивное и осознанное время). Нашли приёмочные тесты.

Ревью вёрстки — `docs/rescan-pilot/design/review-19.md`: ошибки сессии на P1–P3 теперь по каркасу (раньше — тексты оболочки и без строки о телефоне), «Выбрать ›» на 360 не прячется.

## Как проверить

- Страница пациента на моках: `http://127.0.0.1:8763/assets/pilot/index.html#/p/<токен>`. Токены: P4–P6 — `demo-active`, `demo-step-discuss`, `demo-no-doctors`, `demo-paid-format`, `demo-request-accepted`, `demo-request-in-progress`, `demo-request-booked`, `demo-request-cancelled`; P7, P8 — `demo-step-retest`, `demo-retest-today`, `demo-retest-overdue`, `demo-after-visit`, `demo-after-booked`; ошибки — `demo-not-configured`, `demo-error-network`, `demo-error-500`, любой неизвестный токен.
- Ссылка пациента в `rescan_core`: `python -m scripts.issue_link <episode_id> [--base-url …]` — печатает адрес с токеном один раз, в базе только HMAC (`PATIENT_LINK_SECRET`, `PATIENT_LINK_TTL_DAYS`).
- Отправка заявок: `python -m scripts.deliver_crm` из `rescan_core`. Получатели — только из окружения: `CRM_TARGETS`, `NOTIFY_TARGETS`, `CRM_STATUS_SECRET`. В тестах — фейковый приёмник `tests/fake_crm.py` на `127.0.0.1`.
- Команды проверок — раздел «Проверки» задания 19.

## Правки в существующем коде

- `rescan_core/tests/conftest.py` — схема теста командой `SET`, общий пул, таблицы одним запросом (этап 0).
- `rescan_core/app/api/v1/__init__.py` — роутеры `patient` (B6) и `crm` (B7).
- `rescan_core/app/config.py` — `patient_link_secret`, `patient_link_ttl_days` (B6); `crm_targets`, `notify_targets`, `crm_status_secret` и их проверка вне `local`/`test` (B7).
- `rescan_core/app/db/models.py` — ссылки пациента, врачи цели, выбор пациента, `patient_settings` клиники (B6, миграция `20261020_patient_api`).
- `rescan_core/scripts/seed_demo.py` — настройки страницы пациента для демо-клиники (B6).
- `rescan_core/docs/contract.md` — разделы B6 и B7.
- `rescan_core/tests/test_config.py`, `rescan_core/tests/test_b3_acceptance.py` — новые секреты production в наборах настроек.
- `rescan_core/tests/test_crm_delivery.py`, `rescan_core/tests/test_patient_links.py` — секрет соседней задачи в наборах production (стык B6 и B7 при слиянии).
- `medmarshrut_gateway_service/test_gateway.py` — узкое исключение: `https://` только как значение `payment_url` в `web/pilot/js/mocks*.js`; иначе он противоречит `test_pilot_web.py`, который требует ссылку оплаты в мок-данных.
- `medmarshrut_gateway_service/web/pilot/js/router.js`, `api.js`, `mocks.js`, `mocks-patient.js`, `texts.js`, `index.html`, `screens/patient-entry.js`, `patient-goal.js`, `patient-step.js` — маршруты и моки FE3/FE4, переходы с P1–P3.
- `medmarshrut_gateway_service/web/pilot/js/api.js` → `mocks-care.js` — токен `demo-error-network` перенесён в данные FE4, как в контракте.
- `medmarshrut_gateway_service/web/pilot/js/screens/patient-common.js` — ошибки сессии через `handlePatientError` (ревью).
- `medmarshrut_gateway_service/web/pilot/css/tokens.css` — `--avatar`, `--tag-bg`, `--tag-fg` (дизайнер).
- `medmarshrut_gateway_service/pilot_tests/index.js`, `patient-flow.test.js` — подключение новых наборов, переход P3 на `/doctors`, тесты ошибок сессии.
- `demo_stand/web_check.py`, `medmarshrut_gateway_service/test_pilot_web.py` — проверки пилота P4–P8 (тестировщик).
- `demo_stand/web_check.py` — путь с клавиатуры ждёт перерисовку экрана, дата на P7 — у «до» и «просрочено» (координатор, по первому прогону на стенде).
- Чистка (`ce55ef9`): удалены `medmarshrut_path_service/send_report.py`, `create_referral.py`, `route_candidates.py`, `demo_two_cycles.py`, `medmarshrut_clinic_service/accept_referral.py`, `demo.py`, `medmarshrut_medications_service/send_prescription.py`, `demo.py`, контур обучения `medmarshrut_image_service` (`training.py`, `evaluation.py`, `dataset_manifest.py`, `test_training.py`, `TRAINING.md`, `requirements-train.txt`, `reports/`); `PROGRESS_2026-10-03.md` вне git; ссылки в README сервисов снимков и пути.

## Проверки после слияния

SQLite и без базы (`23762ba`):

| Набор | Результат |
|---|---|
| `rescan_core` pytest | 549 прошли, 6 пропущены (только PostgreSQL) |
| ruff / mypy / `alembic upgrade head` + `check` | чисто / 38 файлов без ошибок / «No new upgrade operations detected» |
| сервис снимков / пути / клиники / медикаментов | 15 / 12 / 8 / 10, OK (из снимков ушли 5 тестов контура обучения) |
| шлюз | 123, OK, 6 пропущены (PostgreSQL) |
| node-тесты пилота | 123 из 123 |
| ревью вёрстки, Playwright | 20 состояний × 3 ширины, прокрутки нет, консоль чистая |

PostgreSQL (Supabase, 21.10.2026):

| Набор | Результат |
|---|---|
| `rescan_core`, тесты, которые без базы пропускаются: гонки B4 (2), B6 (2), B7 (2) | 6 из 6 |
| `rescan_core`, миграции: `test_migrations.py` (1), миграция B6 — пустая база, данные B4, откат (3) | 4 из 4 |
| шлюз с `GATEWAY_TEST_DATABASE_URL` | 123, OK, без пропусков |
| `python start.py --smoke` | 22 шага из 22 |
| `python start.py --web-check` | 15 из 15 |

Остальные 545 тестов `rescan_core` на PostgreSQL не прогонялись: полный прогон на Supabase идёт несколько часов, и Claude Code дважды останавливал его из-за нехватки памяти (92 теста прошли до остановки, падений не было). На SQLite они зелёные. Гонка B6 из `test_patient_api.py` однажды упала на нехватке соединений пулера (`EMAXCONNSESSION`); отдельно прошла за 45 с.

`--web-check` в первый запуск: 13 из 15, обе ошибки — в новых проверках пилота, на стенде их раньше не запускали (база была занята). Исправлено в `demo_stand/web_check.py`: путь с клавиатуры ждал адрес, а не перерисовку экрана, и искал радиокнопку на старом экране — теперь старый экран помечается и ожидание идёт до его замены; дата на P7 требуется у «до» и «просрочено», у «сегодня» её нет по тексту дизайнера. Один запуск прервался тайм-аутом 8 с в `pilot_advance` и не повторился.

## Ограничения и предложения команде

- Страница пациента на моках. Live-режим и прокси `/api/patient/*` в шлюзе к `rescan_core` — вместе с FE5.
- Ссылки пациента выдаёт B5 (доставка); сейчас — `scripts.issue_link` для демо.
- P8 и `POST /patient/after-visit/booked` — черновик B8, только в моке, на экране плашка «Демо».
- Битрикс24 шлёт исходящие вебхуки формой и только с id лида: напрямую не принимаем, клиника настраивает робота, который вызывает `POST /v1/crm/status` с JSON.
- Форматы общие для всех врачей клиники: «от» на P4 одинаковое на всех карточках.
- Повтор после неопределённого ответа сети может продублировать заявку в CRM; универсальный приёмник должен дедуплицировать по `request_id`.
- Zoneinfo `Europe/Moscow` на Windows работает только благодаря пакету `tzdata` в `.venv`; в `pyproject.toml` его нет. Предложение: добавить зависимость.
- Деплой в Railway (`www.rescan-clinic.tech`) работает от ветки `develop` и держит пул Supabase (15 сессий): пока он запущен, тесты PostgreSQL, `--smoke` и `--web-check` не получают соединений. Предложение: отдельная база или отдельный проект Supabase для проверок. Переключение сервиса на `mvp` отложено: у Railway сбой, деплои на паузе.
- Решения дизайнера, перенесённые на потом: замена красного акцента клиники по оттенку HSL 340°–20° в `theme.js` с тестом на `#C62828` (в `theme-system.md` и `theme.js` пока не внесено); цена `0` по полису не показывается; окно времени у форматов без визита; название «Быстрый ответ врача» — предложить клиникам «Вопрос врачу онлайн»; памятка P7 — утвердить с клиникой до КТ2.
- Worktree `D:\projects_X\jbd-b7` снят с учёта git, но папка осталась: `.tmp\pytest-*` создала песочница Codex с закрытыми правами. Удалить вручную с правами администратора.
