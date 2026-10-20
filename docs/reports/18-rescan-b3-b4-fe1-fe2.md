# 18. rescan: B3, B4, FE1, FE2

Инструкция: `prompts/18-rescan-b3-b4-fe1-fe2.md`. Работа 19.10.2026 в ветке `mvp`, исполнители в отдельных worktree.

## До начала

Прогон на `a3617e1`:

- `rescan_core`: pytest 56/56 на SQLite и 56/56 на PostgreSQL, ruff и mypy без замечаний, `alembic upgrade head` и `alembic check` без расхождений.
- Снимки 20, путь 12, клиника 8, медикаменты 10, шлюз 108 (с `GATEWAY_TEST_DATABASE_URL`, без пропусков).
- `python start.py --smoke`: 22 шага из 22.
- `python start.py --web-check`: красный. Причина: `SCREENS` в `demo_stand/web_check.py` проверяет экраны пациента, которые задание 13 переадресовало на `#/patient/rsHome` (первый — `patient/services`). `open_screen` ждёт адрес и падает по тайм-ауту 8 с. На локальной базе результат тот же, значит, дело не в удалённой БД.

Окружение:

- PostgreSQL для тестов — временный локальный кластер на 127.0.0.1:55432, только синтетика. Удалённая база Supabase из `.env` в проверках не использовалась.
- Стенд запускался с `GATEWAY_SUPABASE_PROJECT_REF=local`.
- pytest запускался с `--basetemp`: системная Temp недоступна (`PermissionError` в `pytest-of-user`).
- В `.venv` установлены dev-зависимости `rescan_core` из `pyproject.toml`: в нём не было ruff, mypy, cryptography и python-multipart.

## Что сделано

| Коммит | Задача | Исполнитель |
|---|---|---|
| `98ece77` | B3: группы закреплены тестами — повторное событие и смена `PILOT_SALT`/`CONTROL_PERCENT` не меняют группу, доля контроля 24,70% и 24,98% на двух солях, `CONTROL_PERCENT` 0–50, раздел «Группы» в контракте | Codex-1 |
| `2d02326` | Дизайн: `docs/rescan-pilot/design/` (система тем, каркасы и тексты P1–P3 и входа), `web/pilot/css/tokens.css` | дизайнер |
| `3dea727` | Исправлены два дефекта задания 13, из-за которых `--web-check` был красным | координатор |
| `bccce58` | FE1: `web/pilot/` — каркас, роутер, клиент API с моками, тема клиники с проверкой контраста, вход сотрудника и заглушки `#/doctor`, `#/clinic`, плашка «демо» | фронтенд |
| `a49dadc` | FE2: экраны P1–P3 и заглушка «Дальше» на моках, тексты дизайнера, node-тесты в `pilot_tests/` | Codex-2, доделал фронтенд |
| `eaaf29f` | B4: очередь врача — `GET /v1/doctor/queue`, `GET /v1/doctor/step-options`, `POST /v1/doctor/episodes/{id}/step`, `expire_overdue` и `scripts/expire_queue.py`, миграция `20261019_doctor_queue`, раздел B4 в контракте; три замечания ревью Codex исправлены | бэкенд, ревью Codex-1 |
| `5ca6717` | Приёмочные тесты B3 и B4 (чёрный ящик), `test_pilot_web.py`, раздел пилота в `web_check.py`, список экранов `web_check.py` после задания 13 | тестировщик |

Ревью B4 (Codex): CRITICAL и HIGH нет. Исправлены MEDIUM «422 возвращал тело запроса с телефоном», MEDIUM «`weeks: [1000000]` в настройках давал 500» (недели теперь 1–52, иначе клиника не настроена, 503) и LOW «`retest_weeks: null` для другого шага давал 201».

## Как проверить

- Пилот: `python start.py`, затем `http://127.0.0.1:8763/assets/pilot/index.html#/p/<токен>`. Токены: `demo-active`, `demo-consent`, `demo-expired`, `demo-stopped`, `demo-unsubscribed`, `demo-step-discuss`, `demo-step-retest`, `demo-step-followup`, `demo-clinic-a`, `demo-clinic-b` (акцент не проходит контраст, подставлен наш). Сотрудники: `#/staff/login`, логины `demo-doctor` и `demo-manager`, пароль любой непустой.
- Очередь врача: `cd rescan_core`, `python -m alembic upgrade head`, `python -m scripts.seed_demo`, `uvicorn app.main:app`, запросы с `X-Staff-Token: dev-doctor-token`. Истечение срока: `python -m scripts.expire_queue`.
- Node-тесты экранов: `node --test medmarshrut_gateway_service/pilot_tests/`.

## Правки в существующем коде

- `medmarshrut_gateway_service/web/js/main.js`: без адреса открывается стартовый экран роли (`HOME`), а не прежняя главная прототипа (дефект задания 13).
- `medmarshrut_gateway_service/web/js/main.js`: `rsVisits` выбирается по роли окна — раньше экран пациента перекрывал «Приёмы» врача (дефект задания 13).
- `demo_stand/web_check.py`: из `SCREENS` убран `patient/services` (переадресован заданием 13), переходы с «Карты сервисов» проверяются под ролью `staff`; добавлены проверки пилота.
- `rescan_core/app/config.py`: `control_percent` от 0 до 50.
- `rescan_core/app/services/ingest_service.py`: эпизод основной группы получает статус `awaiting_doctor` и срок «время приёма + 24 ч», контрольной — `control`.
- `rescan_core/app/db/models.py`: `Clinic.step_options`, `Episode.queue_deadline_at`.
- `rescan_core/app/api/v1/__init__.py`: подключён роутер врача.
- `rescan_core/scripts/seed_demo.py`: `step_options` демо-клиники, демо-врач `dev-doctor`.
- `rescan_core/app/services/group_service.py`, `rescan_core/docs/contract.md`: описание групп и раздел B4.

## Проверки после слияния

На `5ca6717` плюс правка списка адресов пилота в `web_check.py`:

- `rescan_core`: pytest 206 прошло и 2 пропущено на SQLite (гонки идут только на PostgreSQL), 208/208 на PostgreSQL; ruff и mypy (29 файлов) без замечаний; `alembic upgrade head` и `alembic check` без расхождений.
- Снимки 20, путь 12, клиника 8, медикаменты 10, шлюз 116 (с PostgreSQL, без пропусков; +8 тестов `test_pilot_web.py`).
- Node-тесты пилота: 42/42.
- `python start.py --smoke`: 22 шага из 22.
- `python start.py --web-check`: 12 из 12.

Приёмочные тесты тестировщика писались до кода. При слиянии в них исправлена подготовка данных: настройки клиники (`step_options`, `service_enabled`) писались сырым `UPDATE` и не доходили до объекта в общей сессии теста и приложения, теперь пишутся через ORM. Сравнение текста 503 сделано без учёта регистра. В `web_check.py` цели P3 проверяются у пациента с шагом врача (без шага P3 по замыслу возвращает к выбору ветки), добавлены токены `demo-clinic-a` и `demo-clinic-b`. Проверки не ослаблены.

## Ограничения и предложения команде

- API пациента в контракте фронтенда — черновик B6: `GET /patient/session` с `clinic.phone` и `clinic.privacy_url`, `POST /patient/consent`, `POST /patient/choice`, 404 `link_not_found` на неизвестный токен. Подтвердить в B6.
- Вход сотрудников в пилоте — моковый. Настоящий — через сессию шлюза в FE5 и FE6, токены `rescan_core` в браузер не попадают.
- Планировщика истечения срока нет: `expire_overdue` вызывается скриптом, подключим в B5. B5 должен не слать сообщения эпизодам остановленной клиники и отписавшимся: `expire_overdue` переводит их в `default_message` наравне с остальными.
- `branch_name` в очереди врача пока `null`: МИС передаёт только id филиала. Имена филиалов — из настроек клиники (A1) или отдавать `external_id`, решить в B6.
- Отметка эпизода контрольной группы и отписавшегося пациента — 404, чтобы врач не узнал о группе.
- В `seed_demo.py` ключи темы `logo` и `title`, в контракте фронтенда — `name` и `logo_url`; цели в `seed_demo.py` отличаются от целей дизайнера. Привести к одному в B6.
- Решение продукта: клиника с красным акцентом, который проходит контраст, получит красные кнопки, а в дизайне тревожные акценты запрещены. Отсекать такие цвета вручную при подключении или проверять оттенок в `theme.js`?
- Ветки P2 и цели P3 частично повторяют друг друга; текст согласия — черновик до утверждения юристом (КТ2).
- На SQLite `ready_at` с поясом хранится без пересчёта в UTC и в ответе может быть сдвинут; на PostgreSQL верно. Сроки очереди не затронуты.
- Один из прогонов бэкенда на PostgreSQL однажды завис (123 прошло, 1 ошибка) и больше не воспроизвёлся. Повторить с `-v`, если появится снова.
- Codex в песочнице `workspace-write` не может писать в `.git` worktree: коммиты за него делает координатор.
