# 19. rescan: B6, B7, FE3, FE4 — инструкция для агентов

Дата: 20.10.2026. Источник задач — артефакт «Техдорожная карта Rescan», версия 4 (https://claude.ai/artifact/RXPmsEJ29tpCHXQ5ZGurNd). Если инструкция расходится с картой, верна инструкция: она учитывает то, что уже лежит в репозитории.

Над заданием работают шесть исполнителей: координатор (основная сессия Claude Code), бэкенд, фронтенд, дизайнер, тестировщик (агенты Claude) и два агента Codex. Каждый читает «Общие правила» и свой раздел. В чужие разделы не забегай.

Решения пользователя на сегодня:

- Страница пациента остаётся на моках. Моки повторяют контракт B6 из этого файла дословно. Подключение к `rescan_core` через шлюз — отдельная задача вместе с FE5.
- Настоящей CRM нет. Битрикс24 и универсальный вебхук проверяются на фейковом приёмнике в тестах. Адреса вебхуков — только из переменных окружения.
- База PostgreSQL для проверок — Supabase из `.env`, локальную базу не поднимаем (раздел «Проверки»).

## Готово, когда

1. B6, B7, FE3 и FE4 закрыты по критериям из разделов ниже.
2. Все проверки из раздела «Проверки» зелёные. Числа записаны в отчёт.
3. Отчёт `docs/reports/19-rescan-b6-b7-fe3-fe4.md` написан. Раздел «Что уже сделано» в `CLAUDE.md` и `AGENTS.md` дополнен.
4. В ветке `mvp` по одному коммиту на задачу. Push и merge в другие ветки не делаем.

## Что уже есть

- `rescan_core/` — FastAPI, SQLAlchemy, Alembic. Сделаны B1 (16 таблиц, роли, аудит), B2 (приём событий МИС с HMAC), B3 (группы), B4 (очередь врача, `expire_overdue`). Читай `rescan_core/README.md`, `rescan_core/docs/contract.md`, `docs/reports/18-rescan-b3-b4-fe1-fe2.md`.
- В моделях уже есть `doctors` (`full_name`, `specialty`, `photo_url`, `is_active`), `formats` (`title`, `price_kopecks`, `currency`, `payment_url`), `goals`, `requests` (`doctor_id`, `format_id`, `goal_id`, `window`, `status`, `crm_request_id`), `visits` (`patient_token`, `visit_date`, `doctor_external_id`), `consents`, `outbox` (`topic`, `payload`, `status`, `attempts`, `available_at`). Последняя миграция — `20261019_doctor_queue`.
- Пилот: `medmarshrut_gateway_service/web/pilot/` — каркас, роутер, `api.js` в режиме `mock`, тема клиники, P1–P3 и заглушка `#/p/<token>/next`. Тексты P1–P3 — `docs/rescan-pilot/design/p1-p3.md`. Node-тесты — `medmarshrut_gateway_service/pilot_tests/`.
- Ссылок пациента в базе нет: B5 (доставка) ещё не сделан. B6 заводит таблицу ссылок, B5 потом будет их выдавать.

`web/pilot/...` дальше — это `medmarshrut_gateway_service/web/pilot/...`.

## Общие правила

Обязательны для всех, включая Codex.

1. Прочитай `CLAUDE.md` (для Codex: `AGENTS.md` устарел, при расхождении верен `CLAUDE.md`), этот файл, `rescan_core/README.md` и `rescan_core/docs/contract.md`. Код читай по частям, только нужный задаче.
2. Сервис не ставит диагноз. В rescan нет результатов анализов, значений, диагнозов, признака отклонения и правил «показатель → врач». Порядок врачей не зависит ни от каких медицинских данных. Не добавляй поля и тексты, которые это подразумевают.
3. Только синтетические данные. Никаких реальных телефонов, ФИО, адресов CRM и секретов в коде, тестах, моках и логах. Телефон, токен ссылки и адрес вебхука в логах и аудите запрещены.
4. Токены сотрудников, ссылки пациента и секреты не попадают в браузер дальше, чем нужно: токен пациента живёт только в hash-адресе и заголовке запроса. Всё, что на стенде имитируется, подписано в интерфейсе словом «демо».
5. Работай только в своём worktree и только в своих файлах (таблица «Кто владеет файлами»). Нужна правка чужого файла — напиши координатору, не правь сам.
6. Эндпоинты — только из раздела «Контракты». Чего там нет, того нет. Нужно новое поле или код ответа — предложи координатору.
7. Не переформатируй чужие файлы. Сохраняй кодировку и окончания строк (в репозитории есть BOM и CRLF). Новые файлы — UTF-8 без BOM, LF.
8. Новые зависимости не добавляй. HTTP-клиент для CRM — `urllib.request` из stdlib или уже установленный `httpx`, если он есть в `pyproject.toml`.
9. TDD: сначала тест, он красный, потом код, тест зелёный. Новый эндпоинт или правило доступа — новый тест.
10. Нельзя ослаблять, пропускать и удалять тесты, поднимать допуски, писать «проверено вручную» вместо запуска.
11. Коммить в свою ветку поимённо (`git add <файлы>`), без `git add -A`. Сообщение по-русски: `rescan B6: API пациента`. Не пушь. Codex не коммитит: в песочнице у него нет записи в `.git`, коммит за него делает координатор.
12. Закончил — ответь координатору: что сделано, какие файлы, какие проверки и с какими числами, что не получилось. Застрял после трёх разных попыток — остановись и опиши, что пробовал.

## Кто что делает

| Исполнитель | Задача | Ветка | Worktree |
|---|---|---|---|
| Координатор (Claude Code) | Этап 0, запуск, слияние, финальная проверка, отчёт | `mvp` | основная папка |
| Бэкенд (агент Claude) | B6 API пациента | `rescan/b6` | `../jbd-b6` |
| Codex-1 | B7 заявки в CRM, затем ревью B6 | `rescan/b7` | `../jbd-b7` |
| Фронтенд (агент Claude) | FE3: P4–P6, роутер, моки | `rescan/fe3` | `../jbd-fe3` |
| Codex-2 | FE4: P7–P8 и ошибки пациента | `rescan/fe4` | `../jbd-fe4` |
| Дизайнер (агент Claude) | Каркасы и тексты P4–P8 и ошибок, ревью вёрстки | `rescan/design-19` | `../jbd-design-19` |
| Тестировщик (агент Claude) | Приёмочные тесты B6, B7, проверки страниц пилота, прогон всех наборов | `rescan/qa-19` | `../jbd-qa-19` |

### Кто владеет файлами

| Владелец | Файлы |
|---|---|
| Бэкенд | `rescan_core/app/api/v1/patient.py`, `app/services/patient_service.py`, `app/repositories/patient_repository.py`, `app/schemas/patient.py`, `app/security/patient_link.py`, миграция `migrations/versions/20261020_patient_api.py`, `scripts/issue_link.py`, `tests/test_patient_api.py`, `tests/test_patient_links.py`, `tests/test_patient_doctors.py`. Минимальные правки с тестом: `app/db/models.py`, `app/api/v1/__init__.py`, `app/config.py` (поля B6), `scripts/seed_demo.py`, `docs/contract.md` (раздел B6) |
| Codex-1 | `rescan_core/app/api/v1/crm.py`, `app/services/crm_service.py`, `app/services/crm_transports.py`, `app/schemas/crm.py`, `scripts/deliver_crm.py`, `tests/fake_crm.py`, `tests/test_crm_delivery.py`, `tests/test_crm_status.py`. Минимальные правки с тестом: `app/api/v1/__init__.py`, `app/config.py` (поля B7), `docs/contract.md` (раздел B7) |
| Фронтенд | `web/pilot/js/router.js`, `js/api.js`, `js/mocks.js` (логика ответов), `js/mocks-patient.js` (данные FE3), `js/screens/patient-doctors.js`, `js/screens/patient-request.js`, `js/screens/patient-status.js`, `js/screens/patient-goal.js` (только переход после P3), `css/patient-booking.css`, `index.html` (подключение стилей), `pilot_tests/patient-booking.test.js` |
| Codex-2 | `web/pilot/js/screens/patient-errors.js`, `js/screens/patient-retest.js`, `js/screens/patient-after.js`, `js/screens/patient-step.js` (только переход на P7), `js/mocks-care.js` (данные FE4), `css/patient-care.css`, `pilot_tests/patient-care.test.js` |
| Дизайнер | `docs/rescan-pilot/design/p4-p8.md`, `docs/rescan-pilot/design/review-19.md`, `web/pilot/css/tokens.css` |
| Тестировщик | `rescan_core/tests/test_b6_acceptance.py`, `rescan_core/tests/test_b7_acceptance.py`, `medmarshrut_gateway_service/test_pilot_web.py`, раздел пилота в `demo_stand/web_check.py` |
| Координатор | `docs/reports/19-rescan-b6-b7-fe3-fe4.md`, `CLAUDE.md`, `AGENTS.md`, слияния |

Миграция одна, у бэкенда. B7 обходится существующими таблицами. Если Codex-1 нужна колонка — пишет координатору, колонку добавляет бэкенд в `20261020_patient_api`.

## Порядок работ

**Этап 0, координатор, до запуска агентов.**

1. `git status` чистый, ветка `mvp`.
2. `rescan_core/tests/conftest.py`: схема теста ставится командой `SET search_path` при каждом соединении (пулер Supabase не передаёт параметр `options`), с проверкой, что схема применилась. Отдельный коммит.
3. Базовый прогон всех проверок. Числа — в отчёт, раздел «До начала». Красное до начала работ — остановиться и сказать пользователю.
4. Worktree для каждого исполнителя:
   ```
   git worktree add ..\jbd-b6 -b rescan/b6 mvp
   git worktree add ..\jbd-b7 -b rescan/b7 mvp
   git worktree add ..\jbd-fe3 -b rescan/fe3 mvp
   git worktree add ..\jbd-fe4 -b rescan/fe4 mvp
   git worktree add ..\jbd-design-19 -b rescan/design-19 mvp
   git worktree add ..\jbd-qa-19 -b rescan/qa-19 mvp
   ```
5. Запуск всех шести исполнителей одновременно.

**Этап 1, параллельно.** Дизайнер первым делом сдаёт тексты P4–P8 и ошибок (раздел «Дизайнер», пункты 1–2). До этого фронтенд и Codex-2 пишут временные строки с пометкой `TODO design`. Codex-2 первым коммитом сдаёт `patient-errors.js` с интерфейсом из «Контракта фронтенда»: им пользуются экраны FE3. Бэкенд первым делом пишет миграцию и модели и сообщает координатору: Codex-1 подтягивает их к себе (`git merge rescan/b6`). Тестировщик пишет приёмочные тесты по контрактам: они красные, пока нет кода.

**Этап 2, слияние в `mvp` по готовности, в этом порядке:** B6 → B7 → дизайн → FE4 → FE3 → тесты тестировщика. FE4 раньше FE3, потому что FE3 пользуется `patient-errors.js`. Каждое слияние: `git merge --squash rescan/<x>`, прогон наборов затронутой части, один коммит `rescan <X>: <что>`. Когда B6 готов, Codex-1 делает его ревью (`codex exec review` в `../jbd-b6`). Замечания уровня CRITICAL и HIGH бэкенд исправляет до слияния. Ревью B7 делает бэкенд-агент Claude по тем же уровням.

**Этап 3, приёмка.** Тестировщик гонит все проверки на `mvp`. Дизайнер проходит P4–P8 и ошибки на ширине 360, 390 и 1280 и пишет список правок. Правки вносят владельцы файлов, затем повторный прогон. Координатор пишет отчёт, дополняет «Что уже сделано», делает коммит отчёта и удаляет worktree (`git worktree remove`).

## Контракты

Это предложение координатора, одобренное пользователем вместе с этой инструкцией. Менять — только через координатора.

### B6: API пациента (`rescan_core`)

**Ссылка пациента.** Новая таблица `patient_links`: `id`, `episode_id` (FK), `token_hash` (уникальный), `expires_at`, `revoked_at`, `created_at`. Токен — `secrets.token_urlsafe(32)`, в базе только `HMAC-SHA256(patient_link_secret, токен)` в hex. Модуль `app/security/patient_link.py`: `new_token()`, `hash_token(token)`. Настройки: `patient_link_secret` (dev-значение с префиксом `dev-`, в проде от 32 символов — дописать в `require_production_secrets`) и `patient_link_ttl_days` (по умолчанию 30, от 1 до 90). Выдача ссылки — функция `issue_link(session, episode_id, now)` в `patient_service.py`, возвращает токен один раз. Скрипт `python -m scripts.issue_link <episode_id>` печатает адрес `…/assets/pilot/index.html#/p/<токен>` для демо. HTTP-эндпоинта выдачи нет: ссылки выдаёт B5.

Токен приходит в заголовке `X-Patient-Link`. Нет заголовка, токен не похож на `[A-Za-z0-9_-]{16,128}`, хэша нет в базе, ссылка отозвана, эпизод контрольной группы — один и тот же ответ `404 link_not_found`. Контрольная группа не раскрывается.

**Настройки клиники для пациента.** Новая колонка `clinics.patient_settings` (JSON-строка, как `theme` и `step_options`):

```json
{
  "phone": "+7 000 000-00-00",
  "privacy_url": "https://example-clinic.ru/privacy",
  "timezone": "Europe/Moscow",
  "branches": [{"code": "discuss", "title": "…", "hint": "…"}],
  "windows": [{"code": "morning", "title": "Утром, 8:00–12:00"}],
  "texts": {"p1.active.title": "…"}
}
```

Пусто, не JSON, нет `texts`, `branches`, `windows` или `timezone` — `503 not_configured` «Страница клиники ещё не настроена». Значений по умолчанию в коде нет. `privacy_url` и `payment_url` — только `https://`, иначе поле отдаётся как `null`.

Тема клиники отдаётся как `{name, logo_url, accent}`. В `seed_demo.py` ключи `logo` и `title` переименовать в `logo_url` и `name`. Чтение `clinics.theme` терпит старые ключи только в миграции данных, не в коде ответа.

**Цель → врачи.** Новая таблица `goal_doctors`: `goal_id`, `doctor_id`, `sort_order`, уникальная пара. Клиника кладёт терапевта первым — так в выдаче получается «назначивший, уже был, терапевт».

**Выбор пациента.** Новые колонки `episodes.chosen_branch` (строка до 16) и `episodes.chosen_goal_id` (FK на `goals`).

**Статусы заявки** (`requests.status`): `new` → `sent` → `in_progress` → `booked`, или `cancelled` из любого незавершённого. Пациенту отдаётся упрощённо: `new` и `sent` → `accepted`, `in_progress` → `in_progress`, `booked` → `booked`, `cancelled` → `cancelled`.

Все пути ниже — с префиксом `/v1`, заголовок `X-Patient-Link` обязателен.

`GET /v1/patient/session` → 200:

```json
{
  "state": "active",
  "clinic": {"name": "…", "phone": "…", "privacy_url": "https://…",
             "theme": {"name": "…", "logo_url": null, "accent": "#1D5FD1"}},
  "consent_required": false,
  "doctor_step": {"code": "retest", "retest_weeks": 4, "due_date": "2026-11-17",
                  "retest_state": "before", "doctor_name": "…"},
  "branches": [{"code": "discuss", "title": "…", "hint": "…"}],
  "goals": [{"id": "…", "title": "…"}],
  "choice": {"branch_code": null, "goal_id": "…"},
  "request": {"id": "…", "status": "accepted", "doctor_name": "…",
              "format_title": "…", "window_title": "…", "created_at": "…"},
  "texts": {}
}
```

- `state`: `active`, `expired` (`expires_at` прошёл), `stopped` (`clinics.service_enabled = false`), `unsubscribed` (`patients.opted_out`). Порядок проверки: `unsubscribed`, `stopped`, `expired`. Не `active` — в ответе только `state`, `clinic` и `texts`.
- `doctor_step`: `null`, если врач не отметил шаг (`steps` эпизода с `set_by_doctor_id`). Для `retest` — `due_date` (дата в поясе клиники) и `retest_state`: `before`, `today` или `overdue` по сегодняшней дате в поясе клиники. Для других кодов `retest_weeks`, `due_date`, `retest_state` равны `null`. `doctor_name` — `full_name` врача, отметившего шаг.
- `choice`: `null`, пока пациент не выбрал цель. `request`: последняя незавершённая заявка эпизода или последняя завершённая, иначе `null`.
- `consent_required`: нет записи `consents` с `kind = pd_processing`, `granted = true` у этого пациента.
- Телефона пациента, `patient_token`, других пациентов, групп и данных о здоровье в ответе нет.

`POST /v1/patient/consent` без тела → `200 {"ok": true}`. Пишет `consents` (`pd_processing`, `granted`, `source = link`), повтор ничего не дублирует. Аудит `patient.consent` без ПДн.

`POST /v1/patient/choice` с `{"branch_code": "discuss" | null, "goal_id": "…"}` (`extra="forbid"`) → `200 {"ok": true}`. Если врач отметил шаг, `branch_code` должен быть `null`. Если не отметил — обязателен и из `branches`. `goal_id` — активная цель клиники. Иначе 422. Повторный выбор перезаписывает.

`GET /v1/patient/doctors` → 200 `{"doctors": [{"id", "name", "specialty", "photo_url", "tag"}]}` для выбранной цели (`episodes.chosen_goal_id`). Порядок:

1. Врач, назначивший анализы (`episodes.ordering_doctor_id`), если активен. `tag: "ordering"`.
2. Врачи из `goal_doctors` этой цели, у которых пациент уже был (`visits` по `patient_token` и `doctor_external_id` в этой клинике), сначала последний визит. `tag: "visited"`.
3. Остальные врачи цели по `sort_order`. `tag: null`.

Без повторов, только активные врачи. Пустой список — `200 {"doctors": []}`. На порядок влияют только эти три источника: тест меняет всё остальное и проверяет, что порядок тот же.

`GET /v1/patient/formats` → 200 `{"formats": [{"id", "title", "price_kopecks", "currency", "has_payment"}], "windows": [{"code", "title"}]}`. Активные форматы клиники. Адрес оплаты здесь не отдаётся.

`POST /v1/patient/requests` с `{"doctor_id", "format_id", "window_code"}` (`extra="forbid"`) → `201 {"request_id": "…", "status": "accepted", "payment_url": "https://…" | null}`.

- Врач — из списка `GET /v1/patient/doctors` для выбранной цели, формат активный, окно из `windows`. Иначе 422.
- Создаёт `requests` (`status = new`, `goal_id` из выбора), кладёт в `outbox` запись `topic = crm` с `payload = {"request_id": "…"}` — без телефона и других данных. Аудит `patient.request_created` без ПДн.
- `payment_url` — у формата, если он `https://`, иначе `null`.

Общие ошибки для всех путей B6:

| Код | `code` | Когда |
|---|---|---|
| 404 | `link_not_found` | см. выше |
| 409 | `not_active` | `state` не `active`, кроме `GET /session` |
| 409 | `consent_required` | нет согласия, кроме `GET /session` и `POST /consent` |
| 409 | `choice_required` | `doctors`, `formats`, `requests` до выбора цели |
| 409 | `request_exists` | `POST /requests`, когда у эпизода есть незавершённая заявка |
| 422 | `invalid_input` | тело не по схеме или значение не из списка. Тело запроса в ответ не возвращается |
| 503 | `not_configured` | настройки клиники неполные |

Тело ошибки: `{"detail": {"code": "…", "message": "…"}}`. `message` — по-русски, что случилось и что делать.

Миграция `20261020_patient_api` (`down_revision = "20261019_doctor_queue"`): `patient_links`, `goal_doctors`, `clinics.patient_settings`, `episodes.chosen_branch`, `episodes.chosen_goal_id`, переименование ключей темы в существующих строках `clinics.theme`.

`seed_demo.py`: `patient_settings` с текстами P1–P8 из файлов дизайнера, `goal_doctors` для каждой цели, цели как у дизайнера (`docs/rescan-pilot/design/p1-p3.md`), форматы «Приём в клинике», «Онлайн-консультация», «Быстрый ответ врача» (у последнего `payment_url` на `https://example-clinic.ru/...`).

### B7: заявки в CRM (`rescan_core`)

**Куда отправлять.** Настройки, только из окружения, в базу и логи не попадают:

- `crm_targets`: JSON `{"<clinic_id>": {"kind": "bitrix24" | "webhook", "url": "https://…", "secret": "…"}}`. `secret` обязателен для `webhook`.
- `notify_targets`: JSON `{"<clinic_id>": {"url": "https://…", "secret": "…"}}` — запасной канал, уведомление администратору.
- `crm_status_secret` — подпись входящих статусов.
- В `require_production_secrets`: адреса только `https://`, секреты от 32 символов и без префикса `dev-`. Значения в ошибках не печатаются. В `local` и `test` разрешён `http://127.0.0.1` для фейкового приёмника.

**Отправка.** `deliver_pending(session, now, send)` в `crm_service.py`, скрипт `python -m scripts.deliver_crm`. `send` — функция отправки, тесты подменяют её или поднимают фейковый приёмник `tests/fake_crm.py` (`http.server` на `127.0.0.1`, порт 0). Во внешнюю сеть тесты не ходят.

- Берёт записи `outbox` с `topic = crm`, `status = pending`, `available_at` пусто или `<= now`.
- Данные заявки собирает в момент отправки. Телефон расшифровывается из `contacts` только здесь и не пишется ни в `outbox`, ни в аудит, ни в логи.
- `bitrix24`: `POST <url>/crm.lead.add.json`, поля `TITLE` («Заявка rescan: <цель>»), `PHONE` (`[{"VALUE": …, "VALUE_TYPE": "MOBILE"}]`), `COMMENTS` (врач, формат, окно), `SOURCE_DESCRIPTION` = `rescan`. Ответ `{"result": <id>}` → `requests.crm_request_id`.
- `webhook`: `POST <url>` с JSON `{request_id, clinic_id, patient_token, phone, doctor: {external_id, name}, format: {title, price_kopecks}, window: {code, title}, goal: {title}, created_at}` и заголовками `X-Rescan-Signature`, `X-Rescan-Timestamp` по той же схеме, что вход МИС (`app/security/hmac.py`). Ответ 2xx, необязательное поле `crm_request_id`.
- Успех: `requests.status = sent`, `outbox.status = done`, `processed_at`, аудит `crm.request_sent` (без телефона и адреса).
- Неудача (сеть, тайм-аут 10 с, не 2xx, ответ без `result` у Битрикс24): `attempts + 1`, `available_at = now + 1, 5, 15, 60 минут`. После пятой неудачи `outbox.status = failed`, аудит `crm.request_failed` и запись `outbox` с `topic = notify`, `payload = {"request_id"}`.
- У клиники нет `crm_targets` — сразу `notify`.
- `notify` отправляется тем же `deliver_pending` на `notify_targets` с подписью, тело `{request_id, clinic_id, phone, doctor, format, window, goal, reason}`, где `reason` — `crm_failed` или `no_crm`. Нет и `notify_targets` — `outbox.status = failed`, аудит `crm.no_channel`, ошибка в лог без ПДн.
- Пациент отписался к моменту отправки — не отправлять, заявка `cancelled`, аудит `crm.skipped_opted_out`.
- Две одновременные отправки одной записи `outbox` не отправляют дважды: запись забирается условным `UPDATE … WHERE status = 'pending'` (тест на PostgreSQL).

**Статус обратно из CRM.** `POST /v1/crm/status`, подпись `X-Rescan-Signature` и `X-Rescan-Timestamp` с `crm_status_secret`. Тело (`extra="forbid"`): `{"request_id": "…"}` или `{"crm_request_id": "…"}` (ровно одно) и `"status": "in_progress" | "booked" | "cancelled"`.

- `200 {"request_id", "status"}`; тот же статус повторно — 200 без изменений.
- `401` — подпись неверна или устарела. `404` — заявки нет. `409` — недопустимый переход (`booked` и `cancelled` конечные). `422` — тело не по схеме.
- Аудит `crm.status_changed` (откуда — `crm`).

Битрикс24 шлёт исходящие вебхуки формой и только с id лида. Принимать их напрямую в MVP не будем: клиника настраивает робота, который вызывает наш `POST /v1/crm/status` с JSON. Записать в контракт как ограничение.

**Ручная отметка.** `POST /v1/admin/requests/{request_id}/status`, роль `administrator`, тело `{"status": …}`, те же переходы и коды. Аудит `crm.status_changed` с `actor_id`. Чужая клиника (не `mis_clinic_id`) — 404.

### Контракт фронтенда

Точка входа та же: `/assets/pilot/index.html`. Режим `mock` включён всегда. Пути в `api()` — без `/v1`: `GET /patient/session` в моке соответствует `GET /v1/patient/session` в `rescan_core`, токен из адреса, в заголовок его подставит live-режим позже.

Новые адреса:

| Адрес | Экран | Задача |
|---|---|---|
| `#/p/<token>/doctors` | P4 список врачей | FE3 |
| `#/p/<token>/request?doctor=<id>` | P5 формат, окно, заявка, переход к оплате | FE3 |
| `#/p/<token>/status` | P6 заявка принята и её статус | FE3 |
| `#/p/<token>/retest` | P7 пересдача: дата, памятка, заявка | FE4 |
| `#/p/<token>/after` | P8 напоминание о шаге после визита (черновик B8) | FE4 |

P3 после выбора цели ведёт на `#/p/<token>/doctors`. Заглушка `#/p/<token>/next` уходит из таблицы `ROUTES`, адрес открывает P4. Если у сессии есть `request`, P1 после входа и P4 ведут на `#/p/<token>/status`. Для `retest` P2 показывает кнопку «Когда пересдавать» на `#/p/<token>/retest`.

P4: карточки врачей (фото, если `photo_url` с того же источника, иначе инициалы; имя, специальность; метка для `ordering` и `visited` из текстов; цена «от N ₽» — наименьшая `price_kopecks` из `GET /patient/formats`). Пустой список — текст «связаться с клиникой» и кнопка звонка из `patient-common.js` (`contact()`).

P5: выбор формата (радиокнопки, цена), выбор окна времени (радиокнопки из `windows`), кнопка «Оставить заявку». Никаких полей свободного ввода. Подпись, что запись подтвердит администратор клиники. После `201`: если есть `payment_url`, кнопка-ссылка «Оплатить на сайте клиники» (`rel="noopener noreferrer"`, `target="_blank"`), иначе сразу P6.

P6: статус `accepted`, `in_progress`, `booked`, `cancelled` — нейтральные тексты, без таймеров и красного. Кнопка звонка в клинику.

P7 (FE4): дата пересдачи из `doctor_step.due_date`, состояния `before`, `today`, `overdue` (просрочено — спокойный текст «можно записаться сейчас», без красного), памятка из `texts`, кнопка «Записаться» → `#/p/<token>/goal`.

P8 (FE4): черновик B8, данные только в моке. Поле сессии `after_visit`: `null` или `{"step": {"code": "observe" | "retest" | "specialist" | "none", "due_date": "…" | null, "doctor_name": "…"}, "booked": false}`. Памятка из `texts`, кнопка «Записаться» → `#/p/<token>/goal`, кнопка «Я уже записан» → мок `POST /patient/after-visit/booked` → `{ok: true}`, текст «Хорошо, напоминать не будем». На экране пометка «демо». Бэкенд этот путь сегодня не делает.

Ошибки пациента (FE4), `screens/patient-errors.js`:

```js
export function handlePatientError(err, view, ctx, texts) // → true, если ошибку обработали
```

| Ошибка | Что показать |
|---|---|
| `404 link_not_found` | «Ссылка не найдена», что делать, звонок в клинику, если телефон известен |
| `409 not_active` | перерисовать P1 по свежей сессии |
| `409 consent_required` | `ctx.go` на P1 |
| `409 choice_required` | `ctx.go` на P3 |
| `409 request_exists` | `ctx.go` на P6 |
| `422 invalid_input` | сообщение у формы, выбор не сбрасывается |
| `503 not_configured` | «Страница клиники ещё не настроена», звонок в клинику |
| сеть (`ApiError` со `status` 0, `code` `network`) | «Нет связи», кнопка «Повторить» |
| прочие 5xx | общий текст ошибки сервиса, «Повторить» |

`api.js` в моке умеет отдавать сетевую ошибку: `ApiError(0, 'network', …)` для токена `demo-error-network`. Тексты ошибок, которые нужны до ответа сессии (сеть, `link_not_found`), — в `texts.js` (`SHELL`), их значения тоже от дизайнера: правку `texts.js` делает фронтенд по списку Codex-2.

Мок-токены:

- FE3 (`mocks-patient.js`): `demo-step-discuss` и `demo-active` проходят P3 → P4 → P5 → P6; `demo-no-doctors` (пустой список врачей), `demo-request-accepted`, `demo-request-in-progress`, `demo-request-booked`, `demo-request-cancelled`, `demo-paid-format` (формат с оплатой). Минимум три врача с метками `ordering`, `visited` и без метки.
- FE4 (`mocks-care.js`): `demo-retest-before` (можно расширить `demo-step-retest`), `demo-retest-today`, `demo-retest-overdue`, `demo-after-visit`, `demo-after-booked`, `demo-not-configured`, `demo-error-network`, `demo-error-500`. `mocks.js` склеивает оба раздела, тексты P7–P8 и ошибок из `mocks-care.js` добавляются к `texts` сессии.

Мок повторяет коды и тела ошибок B6 дословно, включая `choice_required` и `request_exists`.

## Бэкенд: B6

1. Прочитай `app/services/queue_service.py`, `app/repositories/queue_repository.py`, `app/api/v1/doctor.py`, `app/db/models.py`, `tests/conftest.py`, раздел B4 в `docs/contract.md`.
2. Первым делом: миграция и модели, тест `alembic upgrade head` на пустой базе и на базе с данными B4. Коммит и сообщение координатору — Codex-1 ждёт модели.
3. Тесты сначала (`tests/test_patient_api.py`, `tests/test_patient_links.py`, `tests/test_patient_doctors.py`): каждый пункт контракта, включая одинаковый 404 для неизвестного, отозванного токена и эпизода контрольной группы; `expired`, `stopped`, `unsubscribed` в правильном порядке; 503 при каждом пропущенном поле `patient_settings`; порядок врачей и его независимость от всего, кроме трёх источников; одна незавершённая заявка на эпизод, включая гонку двух `POST /requests` на PostgreSQL; `outbox` без телефона; отсутствие телефона, токена ссылки и `patient_token` в ответах, аудите и логах (`caplog`); `privacy_url` и `payment_url` не `https` → `null`; тело запроса не возвращается в 422.
4. Код по слоям, как в B4: `patient.py` → `patient_service.py` → `patient_repository.py`, схемы в `schemas/patient.py`.
5. `seed_demo.py`, `scripts/issue_link.py`, раздел B6 в `docs/contract.md`.
6. Проверки `rescan_core` на SQLite и PostgreSQL (раздел «Проверки»).
7. Когда Codex-1 сдаст B7: ревью `../jbd-b7` по уровням CRITICAL / HIGH / MEDIUM / LOW, список — координатору. Сам не правь.

Готово, когда: пациент по ссылке видит шаг врача или ветки, цели, врачей в правильном порядке, форматы и оставляет одну заявку; чужая, отозванная и контрольная ссылки неотличимы; в ответах и журналах нет ПДн; ruff, mypy, alembic check и pytest зелёные.

## Codex-1: B7, затем ревью B6

1. Пока бэкенд не сдал модели — пиши `tests/fake_crm.py` и тесты отправки на заявках, созданных прямо в базе (модель `Request` уже есть). После сообщения координатора: `git merge rescan/b6` в своём worktree.
2. Тесты сначала: `tests/test_crm_delivery.py` (Битрикс24 и вебхук на фейковом приёмнике, подпись вебхука, ретраи по расписанию, пятая неудача → `notify`, нет CRM → `notify`, нет и `notify` → `failed`, отписавшийся пациент, телефона нет в `outbox`, аудите и `caplog`, гонка двух отправок — пометь `needs_postgres`, как в `test_b4_acceptance.py`), `tests/test_crm_status.py` (подпись, все переходы, 404, 409, 422, идемпотентность, ручная отметка администратором, 403 для врача, 404 для чужой клиники).
3. Код: `crm_transports.py` (две отправки и `notify`), `crm_service.py`, `crm.py`, `schemas/crm.py`, `scripts/deliver_crm.py`. Настройки в `app/config.py` — минимальный дифф с тестом в `tests/test_crm_delivery.py`.
4. Раздел B7 в `docs/contract.md`, включая ограничение про исходящие вебхуки Битрикс24.
5. Проверки `rescan_core` только на SQLite: адреса Supabase у Codex нет, PostgreSQL прогоняет координатор.
6. Когда координатор сообщит о готовности B6: `codex exec review` в `../jbd-b6`, список замечаний с уровнями. Сам не правь.

Готово, когда: заявка приходит в фейковые Битрикс24 и вебхук с правильными полями, при сбое повторяется и уходит администратору, статус возвращается вебхуком и ручной отметкой, телефона нет нигде, кроме тела запроса в CRM.

## Фронтенд: FE3

1. Посмотри `web/pilot/js/screens/patient-common.js`, `patient-state.js`, `patient-goal.js`, `css/patient.css`, `css/tokens.css`, `docs/rescan-pilot/design/p1-p3.md`.
2. Первым делом: маршруты FE3 и FE4 в `router.js` (FE4 — с загрузкой модулей Codex-2 по именам из «Кто владеет файлами»), логика `mocks.js` для всех путей из контракта, включая `POST /patient/after-visit/booked`, импорт `mocks-care.js`. Сообщи координатору: Codex-2 подтянет этот коммит.
3. P4, P5, P6 по «Контракту фронтенда». Тексты — из `texts` сессии, значения — из `docs/rescan-pilot/design/p4-p8.md`.
4. Ошибки — через `handlePatientError` из `patient-errors.js`. Пока Codex-2 его не сдал, временная заглушка в своём файле, перед слиянием её быть не должно.
5. Переход P3 → P4 в `patient-goal.js`. P1 и P4 ведут на P6, если заявка есть.
6. Без полей свободного ввода, без `textarea`. Всё с сервера — через `safe()`. Фото врача — только с того же источника.
7. Node-тесты в `pilot_tests/patient-booking.test.js`: порядок карточек как в ответе, цена «от», пустой список, повторная заявка → P6, ссылка на оплату только `https`.
8. Адаптив 360–1280 без горизонтальной прокрутки, Tab и Enter, видимый фокус.

Готово, когда: каждое состояние P4–P6 открывается по своему мок-токену, путь P1 → P6 проходится с клавиатуры, консоль чистая, CSP не нарушен, node-тесты и `test_pilot_web.py` зелёные.

## Codex-2: FE4

1. Первым коммитом в течение часа — `screens/patient-errors.js` с `handlePatientError` и разметкой ошибок по таблице из контракта. Сообщи координатору: фронтенд им пользуется. Нужны строки в `texts.js` — пришли список координатору.
2. Пока фронтенд не сдал маршруты и логику моков — пиши экраны и `mocks-care.js` по контракту. После его коммита: `git merge rescan/fe3` в своём worktree.
3. P7 `screens/patient-retest.js`: три состояния, дата в формате «17 ноября», памятка, кнопка записи.
4. P8 `screens/patient-after.js`: шаг после визита, памятка, «Записаться», «Я уже записан», пометка «демо».
5. Переход на P7 из P2 для `retest` в `patient-step.js`, минимальный дифф.
6. Без тревожных акцентов: без красного, восклицаний, таймеров. Просрочка — спокойным текстом.
7. Node-тесты в `pilot_tests/patient-care.test.js`: три состояния P7, обе ветки P8, каждая строка таблицы ошибок.

Готово, когда: каждое состояние P7, P8 и каждая ошибка открываются по своему мок-токену, на 360, 390 и 1280 нет горизонтальной прокрутки, консоль чистая, проверки тестировщика по запрещённым словам зелёные.

## Дизайнер

Сдать в первые полтора часа, по порядку:

1. `docs/rescan-pilot/design/p4-p8.md`: каркасы P4–P8 во всех состояниях из контракта (текстовые схемы блоков сверху вниз) и все тексты дословно с ключами для `texts` (`p4.*`, `p5.*`, `p6.*`, `p7.*`, `p8.*`, `err.*`). Тон как в `p1-p3.md`. Отдельно: как подать цену быстрого ответа врача как услугу клиники; как пациент понимает, что запись подтвердит администратор, а не система; метки «ваш врач» и «вы уже были».
2. Окна времени и форматы для демо-клиник — в том же файле, бэкенд берёт их в `seed_demo.py`.
3. Если нужны новые токены — `web/pilot/css/tokens.css`.

Потом:

4. Ответ на открытый вопрос отчёта 18: что делать с клиникой, у которой красный акцент проходит контраст. `theme-system.md` не правь: это файл прошлого задания. Решение напиши в разделе «Решения» файла `p4-p8.md`, координатор перенесёт его в отчёт.
5. Тексты проверить на запрещённые слова: «расшифровка», «риск», «срочно», «отклонение», «диагноз».
6. На этапе 3 — ревью P4–P8 и ошибок на 360, 390 и 1280 по скриншотам Playwright. Правки одним списком в `docs/rescan-pilot/design/review-19.md`: экран, ширина, что не так, как должно быть.

Готово, когда: экраны собраны без пометок `TODO design`, список правок ревью закрыт или перенесён координатором в «Ограничения» отчёта.

## Тестировщик

1. Этап 1, сразу: `rescan_core/tests/test_b6_acceptance.py` и `rescan_core/tests/test_b7_acceptance.py` по разделу «Контракты» как чёрный ящик через HTTP (настройки и данные — через ORM, как исправлено в отчёте 18). Для B7 — фейковый приёмник на `127.0.0.1`. До слияния кода они красные — это ожидаемо, зафиксируй.
2. `medmarshrut_gateway_service/test_pilot_web.py`: новые экраны под теми же правилами (запрещённые слова, нет `textarea` и свободного ввода, нет хранилищ браузера, обработчиков в разметке, внешних адресов, кроме ссылки оплаты из данных; нет строк, похожих на токены).
3. Раздел пилота в `demo_stand/web_check.py`: P4–P8 во всех мок-состояниях, путь P1 → P6 с клавиатуры, каждая ошибка из таблицы. Ширины 360, 390, 1280. Ошибки консоли, нарушения CSP и горизонтальная прокрутка — провал. Существующие проверки не меняй.
4. Этап 3: полный прогон раздела «Проверки» на `mvp` после всех слияний. Числа — координатору. Красное — к владельцу файла с текстом ошибки.

Готово, когда: приёмочные тесты B6 и B7 зелёные на SQLite и PostgreSQL, проверки страниц пилота зелёные, полный прогон зелёный.

## Проверки

В `rescan_core`:

```
python -B -m pytest -p no:cacheprovider --basetemp <папка во временной папке сессии>
python -B -m ruff check .
python -B -m mypy app
```

`alembic upgrade head` и `alembic check` — на пустой SQLite-базе в файле, с `DATABASE_URL=sqlite+pysqlite:///<путь>`. Не запускай alembic с адресом Supabase: таблицы попадут в схему `public`, которую Supabase открывает наружу через REST. PostgreSQL для миграций проверяют тесты (`test_migrations.py` и тесты миграции B6) во временной схеме.

PostgreSQL — Supabase из `.env`. Адрес никуда не печатаем и в файлы не пишем. Запуск через обёртку координатора, которая передаёт `RESCAN_TEST_DATABASE_URL` и `GATEWAY_TEST_DATABASE_URL` только дочернему процессу:

```
python C:\Users\user\AppData\Local\Temp\claude\D--projects-X-Just-Business-Darling\01d7719a-0284-40c2-8c8c-1d26c83ed7ce\scratchpad\envrun.py <папка> python -B -m pytest -p no:cacheprovider --basetemp <папка>
```

Каждый тест создаёт и удаляет свою схему `test_<hex>`. Прогон на Supabase идёт медленно (сервер во Франкфурте), а у пулера ограничено число соединений. Поэтому PostgreSQL гоняют только бэкенд (свои файлы тестов), тестировщик (свои файлы, а на этапе 3 — всё) и координатор, и не одновременно: перед прогоном напиши координатору. Codex и фронтенд PostgreSQL не запускают. Без адреса тесты PostgreSQL пропускаются — так и пиши, а не «пройдено».

В корне репозитория:

```
python -B -m unittest discover -s ./medmarshrut_image_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_path_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_clinic_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_medications_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_gateway_service -p "test_*.py" -v
node --test medmarshrut_gateway_service/pilot_tests/
python start.py --smoke
python start.py --web-check
```

`--smoke` и `--web-check` поднимают стенд на портах 8763–8767 и пересоздают схему шлюза из `.env`. Их запускает только тестировщик или координатор, по одному. Не оставляй `python start.py` работать в фоне.

## Запуск Codex

PowerShell, из основной папки. Инструкция уходит в Codex через stdin, задача — аргументом. Адреса Supabase и `.env` Codex не получает. Пути для `--add-dir` — абсолютные.

```
Get-Content -Raw prompts\19-rescan-b6-b7-fe3-fe4.md | codex exec -C ..\jbd-b7 -s workspace-write -o $env:TEMP\codex-b7.txt "Ты — Codex-1. Выполни раздел «Codex-1: B7, затем ревью B6» из инструкции ниже и соблюдай «Общие правила». Ревью B6 не начинай, пока координатор не попросит."

Get-Content -Raw prompts\19-rescan-b6-b7-fe3-fe4.md | codex exec -C ..\jbd-fe4 -s workspace-write -o $env:TEMP\codex-fe4.txt "Ты — Codex-2. Выполни раздел «Codex-2: FE4» из инструкции ниже и соблюдай «Общие правила»."
```

Ревью B6 — отдельным запуском, когда бэкенд закончит:

```
codex exec review -C ..\jbd-b6 -o $env:TEMP\codex-review-b6.txt
```

Итог Codex читается из файла `-o`. Координатор запускает их в фоне и не ждёт активно: Claude Code сообщит, когда процесс завершится.

## Отчёт координатора

`docs/reports/19-rescan-b6-b7-fe3-fe4.md`:

- До начала: числа базового прогона и правка `conftest.py` под Supabase.
- Что сделано по каждой задаче, кто делал.
- Как проверить: мок-токены, `issue_link`, `deliver_crm`, команды.
- Каждая правка в существующем коде — отдельной строкой: файл и зачем.
- Проверки после слияния: числа по каждому набору, SQLite и PostgreSQL отдельно.
- Ограничения и предложения команде: live-режим страницы пациента и прокси в шлюзе (вместе с FE5); выдача ссылок появится в B5; P8 и `after-visit/booked` — черновик B8; исходящие вебхуки Битрикс24 через робота; форматы общие для всех врачей клиники; решения дизайнера, перенесённые на потом.
