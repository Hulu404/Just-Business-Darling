# 18. rescan: B3, B4, FE1, FE2 — инструкция для агентов

Дата: 19.10.2026. Источник задач — артефакт «Техдорожная карта Rescan», версия 4 (https://claude.ai/artifact/RXPmsEJ29tpCHXQ5ZGurNd). Если инструкция расходится с картой, верна инструкция: она учитывает то, что уже лежит в репозитории.

Над заданием работают шесть исполнителей: координатор (основная сессия Claude Code), бэкенд, фронтенд, дизайнер, тестировщик (агенты Claude) и два агента Codex. Каждый читает «Общие правила» и свой раздел. В чужие разделы не забегай.

## Готово, когда

1. B3, B4, FE1 и FE2 закрыты по критериям из разделов ниже.
2. Все проверки из раздела «Проверки» зелёные. Числа записаны в отчёт.
3. Отчёт `docs/reports/18-rescan-b3-b4-fe1-fe2.md` написан. Раздел «Что уже сделано» в `CLAUDE.md` и `AGENTS.md` дополнен.
4. В ветке `mvp` по одному коммиту на задачу. Push и merge в другие ветки не делаем.

## Что уже есть

- `rescan_core/` — FastAPI, SQLAlchemy, Alembic, PostgreSQL (тесты также на SQLite). Сделаны B1 (16 таблиц, роли, аудит), B2 (`POST /v1/mis/results-ready`, `POST /v1/mis/visits-csv`, HMAC с timestamp) и основа B3 (`app/services/group_service.py`, группа пишется в `patients.group` при первом событии). Подробности: `rescan_core/README.md`, `rescan_core/docs/contract.md`, `docs/reports/17-rescan-core-security.md`.
- Роли сотрудников в `rescan_core`: заголовок `X-Staff-Token`, словарь `staff_tokens` в настройках, `require_roles(...)` в `app/security/roles.py`.
- У клиники уже есть `clinics.theme` (JSON-строка с токенами темы) и `clinics.service_enabled` (стоп-кнопка).
- Шлюз `medmarshrut_gateway_service/` раздаёт файлы из `web/` по адресу `/assets/<путь>`, к `.html` добавляет CSP. Компоненты и токены приложения пациента rescan: `web/phone.css`, `web/rescan.css`, `web/js/rescan-phone.js`.
- Страниц пилота (пациент по ссылке, вход врача и клиники) пока нет. API пациента (B6) тоже нет: сегодня фронтенд работает на моках.

## Общие правила

Обязательны для всех, включая Codex.

1. Прочитай `CLAUDE.md` (для Codex: `AGENTS.md` устарел, при расхождении верен `CLAUDE.md`), этот файл, `rescan_core/README.md` и `rescan_core/docs/contract.md`. Код читай по частям, только нужный задаче.
2. Сервис не ставит диагноз. В rescan нет результатов анализов, значений, диагнозов, признака отклонения и правил «показатель → врач». Не добавляй поля и тексты, которые это подразумевают.
3. Только синтетические данные. Никаких реальных телефонов, ФИО, секретов в коде, тестах, моках и логах. Телефон в логах и аудите запрещён.
4. Токены сотрудников и секреты не попадают в браузер. Всё, что на стенде имитируется, подписано в интерфейсе словом «демо».
5. Работай только в своём worktree и только в своих файлах (таблица «Кто владеет файлами»). Нужна правка чужого файла — напиши координатору, не правь сам.
6. Эндпоинты — только из раздела «Контракты» ниже. Чего там нет, того нет. Нужно новое поле или код ответа — предложи координатору.
7. Не переформатируй чужие файлы. Сохраняй кодировку и окончания строк (в репозитории есть BOM и CRLF). Новые файлы — UTF-8 без BOM, LF.
8. Новые зависимости не добавляй.
9. TDD: сначала тест, он красный, потом код, тест зелёный. Новый эндпоинт или правило доступа — новый тест.
10. Нельзя ослаблять, пропускать и удалять тесты, поднимать допуски, писать «проверено вручную» вместо запуска.
11. Коммить в свою ветку поимённо (`git add <файлы>`), без `git add -A`. Сообщение по-русски: `rescan B4: очередь врача`. Не пушь.
12. Закончил — ответь координатору: что сделано, какие файлы, какие проверки и с какими числами, что не получилось. Застрял после трёх разных попыток — остановись и опиши, что пробовал.

## Кто что делает

| Исполнитель | Задача | Ветка | Worktree |
|---|---|---|---|
| Координатор (Claude Code) | Этап 0, запуск, слияние, финальная проверка, отчёт | `mvp` | основная папка |
| Бэкенд (агент Claude) | B4 очередь врача | `rescan/b4` | `../jbd-b4` |
| Codex-1 | B3, затем ревью B4 | `rescan/b3` | `../jbd-b3` |
| Фронтенд (агент Claude) | FE1 каркас, темы, вход сотрудников, моки | `rescan/fe1` | `../jbd-fe1` |
| Codex-2 | FE2 экраны P1–P3 | `rescan/fe2` | `../jbd-fe2` |
| Дизайнер (агент Claude) | Система тем, каркасы и тексты P1–P3 и входа, ревью вёрстки | `rescan/design` | `../jbd-design` |
| Тестировщик (агент Claude) | Приёмочные тесты B3, B4, проверки страниц пилота, прогон всех наборов | `rescan/qa` | `../jbd-qa` |

### Кто владеет файлами

| Владелец | Файлы |
|---|---|
| Бэкенд | `rescan_core/app/api/v1/doctor.py`, `rescan_core/app/services/queue_service.py`, `rescan_core/app/repositories/queue_repository.py`, `rescan_core/app/schemas/queue.py`, `rescan_core/scripts/expire_queue.py`, новая миграция в `rescan_core/migrations/versions/`, `rescan_core/tests/test_doctor_queue.py`, `rescan_core/tests/test_queue_expire.py`. Минимальные правки с тестом: `app/api/v1/__init__.py`, `app/services/ingest_service.py`, `app/db/models.py`, `scripts/seed_demo.py`, `docs/contract.md` (раздел B4) |
| Codex-1 | `rescan_core/app/services/group_service.py`, `rescan_core/tests/test_groups.py`, `rescan_core/tests/test_groups_ingest.py`, `rescan_core/docs/contract.md` (раздел «Группы»). Минимальная правка с тестом: `app/config.py` |
| Фронтенд | `medmarshrut_gateway_service/web/pilot/index.html`, `web/pilot/js/{app,router,api,mocks,theme,ui,staff}.js`, `web/pilot/css/base.css`, `web/pilot/css/staff.css` |
| Codex-2 | `web/pilot/js/screens/patient-*.js`, `web/pilot/css/patient.css`, раздел `PATIENT` в `web/pilot/js/mocks.js` (только данные, без логики) |
| Дизайнер | `docs/rescan-pilot/design/*.md`, `web/pilot/css/tokens.css` |
| Тестировщик | `rescan_core/tests/test_b3_acceptance.py`, `rescan_core/tests/test_b4_acceptance.py`, `medmarshrut_gateway_service/test_pilot_web.py`, раздел пилота в `demo_stand/web_check.py` |
| Координатор | `docs/reports/18-rescan-b3-b4-fe1-fe2.md`, `CLAUDE.md`, `AGENTS.md`, слияния |

`web/pilot/...` дальше — это `medmarshrut_gateway_service/web/pilot/...`.

## Порядок работ

**Этап 0, координатор, до запуска агентов (≈30 минут).**

1. `git status` чистый, ветка `mvp`.
2. Базовый прогон всех проверок из раздела «Проверки». Числа — в отчёт, раздел «До начала». Если что-то красное до начала работ (в отчёте 13 `--web-check` был красным из-за тайм-аута общей БД), остановись и скажи пользователю: критерий «все тесты зелёные» иначе не выполнить.
3. Worktree для каждого исполнителя:
   ```
   git worktree add ..\jbd-b3 -b rescan/b3 mvp
   git worktree add ..\jbd-b4 -b rescan/b4 mvp
   git worktree add ..\jbd-fe1 -b rescan/fe1 mvp
   git worktree add ..\jbd-fe2 -b rescan/fe2 mvp
   git worktree add ..\jbd-design -b rescan/design mvp
   git worktree add ..\jbd-qa -b rescan/qa mvp
   ```
4. Запуск всех шести исполнителей одновременно (раздел «Запуск Codex» и обычный Agent tool для Claude).

**Этап 1, параллельно.** Дизайнер первым делом сдаёт токены и тексты P1–P3 (раздел «Дизайнер», пункты 1–3) — это нужно фронтенду. До этого фронтенд и Codex-2 работают на временных значениях из раздела «Контракт фронтенда». Тестировщик пишет приёмочные тесты по контрактам: они красные, пока нет кода.

**Этап 2, слияние в `mvp` по готовности, в этом порядке:** B3 → B4 → дизайн → FE1 → FE2 → тесты тестировщика. Каждое слияние: `git merge --squash rescan/<x>`, прогон наборов затронутой части, один коммит `rescan <X>: <что>`. После B4 Codex-1 делает ревью B4 (`codex exec review` в `../jbd-b4`), замечания уровня CRITICAL и HIGH бэкенд исправляет до слияния.

**Этап 3, приёмка.** Тестировщик гонит все проверки на `mvp`. Дизайнер проходит экраны P1–P3 и вход на ширине 360, 390 и 1280 и пишет список правок. Правки вносят владельцы файлов, затем повторный прогон. Координатор пишет отчёт, дополняет «Что уже сделано», делает коммит отчёта и удаляет worktree (`git worktree remove`).

## Контракты

Это предложение координатора, одобренное пользователем вместе с этой инструкцией. Менять — только через координатора.

### B4: очередь врача (`rescan_core`)

Статусы эпизода (`episodes.status`):

- `awaiting_doctor` — основная группа после приёма события. Эпизод в очереди своего врача.
- `control` — контрольная группа. В очередь не попадает, сообщений не получает.
- `doctor_marked` — врач отметил шаг.
- `default_message` — 24 часа прошли без отметки, уходит стандартное сообщение.

Срок отметки: `queue_deadline_at = время приёма события + 24 часа` (новая колонка `episodes.queue_deadline_at`, миграция). Не от `ready_at`: событие может прийти с опозданием.

Врач сотрудника: `actor_id` из `staff_tokens` равен `doctors.external_id` в клинике интеграции. Нет такого врача — 403.

Список шагов: коды фиксированы в коде — `discuss` («обсудить»), `retest` («пересдача через N недель»), `followup` («контроль у меня»). Клиника включает подмножество и задаёт тексты в настройках: новая колонка `clinics.step_options` (JSON-строка, как `theme`), `seed_demo.py` её заполняет. Если в настройках пусто, очередь отвечает 503 «список шагов клиники не настроен» — без значений по умолчанию в коде.

`GET /v1/doctor/queue` — роль `doctor`.

```json
{
  "server_time": "2026-10-19T10:00:00Z",
  "items": [
    {"episode_id": "…", "patient_token": "…", "branch_name": "…",
     "ready_at": "…", "queue_deadline_at": "…"}
  ]
}
```

Только эпизоды этого врача в статусе `awaiting_doctor`, со сроком в будущем, без отписавшихся пациентов. Сортировка по `queue_deadline_at`. Пусто — 200 и `"items": []`. Телефона, ФИО и данных о здоровье в ответе нет. Клиника остановлена (`service_enabled = false`) — 403.

`GET /v1/doctor/step-options` — роль `doctor`.

```json
{"options": [{"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]}]}
```

`POST /v1/doctor/episodes/{episode_id}/step` — роль `doctor`. Тело с `extra="forbid"`:

```json
{"code": "retest", "retest_weeks": 4}
```

- `201` и `{"episode_id": "…", "step_id": "…", "status": "doctor_marked"}`.
- `404` — эпизода нет или он чужой (не раскрываем, что он существует).
- `409` — уже отмечен или срок прошёл.
- `422` — неизвестный код, код выключен в клинике, `retest_weeks` не из списка или передан не для `retest`, тело — массив.
- Создаёт `steps` (`kind = code`, `set_by_doctor_id`, `set_at`, `due_date` для `retest`), пишет аудит `doctor.step_marked` (кто и когда, без ПДн), кладёт в `outbox` событие `episode.doctor_marked` для B5.
- Переход статуса — условным `UPDATE … WHERE status = 'awaiting_doctor'`: две одновременные отметки или отметка и истечение срока дают ровно один результат.
- Массовой отметки нет: ни эндпоинта со списком эпизодов, ни параметра «отметить всех».

Истечение срока — функция `expire_overdue(session, now)` в `queue_service.py` и скрипт `python -m scripts.expire_queue`. Эпизоды `awaiting_doctor` с `queue_deadline_at <= now` переходят в `default_message`, в `outbox` — `episode.default_message`, в аудит — `queue.expired` от имени `system`. Повторный запуск ничего не меняет. Время передаётся параметром, чтобы тесты не ждали 24 часа. HTTP-эндпоинта для этого нет; планировщик подключим в B5.

### B3: группы (`rescan_core`)

Код и правило уже есть. Остаётся доказать и закрепить:

- повторное событие того же пациента даёт ту же группу и в ответе, и в новом эпизоде;
- смена `pilot_salt` или `control_percent` после первого события не меняет группу уже записанного пациента;
- доля контроля на 10 000 синтетических токенов 25 ± 1% (тест есть) и на другой соли тоже;
- `control_percent` вне 0–50 и пустая `pilot_salt` вне `local`/`test` — ошибка конфигурации без печати значения;
- эпизод контрольной группы получает статус `control` (правку в `ingest_service.py` делает бэкенд в B4, Codex-1 только проверяет её тестом после слияния B4).

### Контракт фронтенда

Отдельная точка входа пилота: `http://127.0.0.1:8763/assets/pilot/index.html`. Существующее приложение МедМаршрута не трогаем. Шлюз менять не нужно: он уже раздаёт `/assets/…` с CSP.

Адреса (hash, токен пациента не уходит на сервер в адресе запроса страницы):

| Адрес | Экран | Задача |
|---|---|---|
| `#/p/<token>` | P1 вход по ссылке и согласие | FE2 |
| `#/p/<token>/step` | P2 шаг врача или три ветки | FE2 |
| `#/p/<token>/goal` | P3 цель визита | FE2 |
| `#/p/<token>/next` | заглушка «Дальше — выбор врача», демо | FE2 |
| `#/staff/login` | вход врача и клиники | FE1 |
| `#/doctor` | заглушка «Очередь появится в FE5», демо | FE1 |
| `#/clinic` | заглушка «Раздел клиники появится в FE6», демо | FE1 |

Модуль экрана: `export function render(view, ctx)`, где `view` — элемент `#view`, а `ctx = { api, go, safe, theme, params, texts }`. Экран не трогает адрес и тему напрямую, только через `go()` и `ctx.theme`. `router.js` регистрирует экраны таблицей `ROUTES = [{pattern, load}]`, где `load` — динамический `import()`.

`api.js`: `api(method, path, body)` возвращает `Promise` с данными или бросает `ApiError { status, code, message }`. Режим `mock` включён на этом этапе всегда; в шапке видна плашка «демо». Режим `live` пока бросает `ApiError(503, "live_disabled", "Сервис ещё не подключён.")`.

Мок-данные пациента (`mocks.js`, раздел `PATIENT`) — черновик B6, бэкенд подтвердит его в задаче B6:

- `GET /patient/session` → `{ state, clinic: { name, theme }, consent_required, doctor_step, branches, goals, texts }`
  - `state`: `active` | `expired` | `stopped` | `unsubscribed`;
  - `doctor_step`: `null` или `{ code: "discuss" | "retest" | "followup", retest_weeks, doctor_name }`;
  - `branches`: три ветки без отметки врача, `[{ code, title, hint }]`;
  - `goals`: четыре цели `[{ id, title }]`;
  - `texts`: все тексты экранов P1–P3 из «настроек клиники».
- `POST /patient/consent` → `{ ok: true }`.
- `POST /patient/choice` с `{ branch_code | null, goal_id }` → `{ ok: true }`.

Мок различает токены `demo-active`, `demo-step-discuss`, `demo-step-retest`, `demo-step-followup`, `demo-expired`, `demo-stopped`, `demo-unsubscribed`, `demo-consent`, чтобы каждое состояние открывалось по адресу. Минимум две клиники: `demo-clinic-a` с хорошим акцентом и `demo-clinic-b` с акцентом, который не проходит контраст.

Мок-вход сотрудника (`POST /staff/login` с `{ login, password }`): логины `demo-doctor` и `demo-manager`, ответ `{ role, display_name }`. Пароль и токены в браузере не хранятся и в `X-Staff-Token` не превращаются. Настоящий вход будет через сессию шлюза в FE5/FE6.

Тема: `theme.js` применяет `{ name, logo_url, accent }` к переменным `--clinic-accent`, `--clinic-on-accent`, `--clinic-name`. Если контраст акцента с белым ниже 4,5:1, подставляется наш акцент из `tokens.css`. Логотип только с того же источника (`/assets/...`), иначе CSP; нет логотипа — название клиники текстом.

Временные значения до сдачи дизайнера: `--clinic-accent: #0B7A83`, тексты — короткие нейтральные строки с пометкой `TODO design`. Перед слиянием пометок `TODO design` быть не должно.

## Бэкенд: B4

1. Прочитай `app/services/ingest_service.py`, `app/repositories/event_repository.py`, `app/security/roles.py`, `app/db/models.py`, `tests/conftest.py`.
2. Тесты сначала (`tests/test_doctor_queue.py`, `tests/test_queue_expire.py`): каждый пункт контракта B4, включая 404 на чужой эпизод, 409 на повтор, 422 на массив, 403 на остановленную клинику, гонку двух отметок и отметки с истечением на PostgreSQL, отсутствие телефона в ответах и аудите, отсутствие пути с массовой отметкой в `app.openapi()`.
3. Миграция: `episodes.queue_deadline_at`, `clinics.step_options`. Проверь `alembic upgrade head` на пустой базе и на базе с данными, затем `alembic check`.
4. Правка `ingest_service.py`: статус `awaiting_doctor` или `control` и `queue_deadline_at` при создании эпизода. Минимальный дифф, тест на оба статуса.
5. Эндпоинты в `app/api/v1/doctor.py`, логика в `queue_service.py`, запросы в `queue_repository.py`, схемы в `schemas/queue.py`. Стиль — как в `mis.py` и `event_repository.py`.
6. `seed_demo.py`: `step_options` демо-клиники и демо-врач с `external_id = dev-doctor`.
7. Раздел B4 в `docs/contract.md`.
8. Проверки `rescan_core` (раздел «Проверки») на SQLite и PostgreSQL.

Готово, когда: врач видит только своих пациентов основной группы; отметка по одному пишет врача и время в журнал; через 24 часа без отметки эпизод уходит в `default_message`; массового действия в API нет; ruff, mypy, alembic check и pytest зелёные.

## Codex-1: B3, затем ревью B4

1. Тесты по контракту B3 в `tests/test_groups.py` и `tests/test_groups_ingest.py` (через HTTP с подписью, как в `tests/test_ingest.py`).
2. Проверка `control_percent` и `pilot_salt` в `app/config.py`, если её нет. Минимальный дифф.
3. Раздел «Группы» в `docs/contract.md`: правило, соль, что группа не пересчитывается.
4. Проверки `rescan_core`. Коммит `rescan B3: группы закреплены тестами`.
5. Когда координатор сообщит о готовности B4: `codex exec review` в `../jbd-b4`, список замечаний с уровнями CRITICAL / HIGH / MEDIUM / LOW. Сам не правь.

Готово, когда: доля контроля 25 ± 1% на двух солях, повторное событие и смена настроек не меняют группу, конфигурация с неверными значениями падает понятной ошибкой.

## Фронтенд: FE1

1. Посмотри `web/js/rescan-phone.js`, `web/phone.css`, `web/rescan.css`, `web/js/api.js`, `web/js/ui.js`: берём компоненты и подход, код не копируем вслепую.
2. Первым коммитом в течение часа — каркас с интерфейсами из «Контракта фронтенда»: `index.html` (без встроенных скриптов, один `<script type="module" src="js/app.js">`), `router.js`, `api.js`, `ui.js` с `safe()`, `theme.js`, пустой `mocks.js` с разделами `PATIENT` и `STAFF`. Сообщи координатору: Codex-2 подтянет этот коммит к себе.
3. Тема клиники с проверкой контраста и подстановкой своего акцента.
4. Экран входа сотрудника и заглушки `#/doctor`, `#/clinic` с ролью из мок-входа. Неверный логин: «Логин или пароль не подошли. Проверьте и попробуйте ещё раз».
5. Общие состояния: загрузка (`.card.skeleton`, её ждёт `wait_ready` в `web_check.py`), ошибка сервиса, «страница не найдена».
6. Плашка «демо» в шапке при режиме `mock`.
7. Адаптив 360–1280 без горизонтальной прокрутки. Клавиатура: все действия доступны с Tab и Enter, фокус виден.

Готово, когда: страница открывается по `/assets/pilot/index.html`, роутинг работает по всем адресам из таблицы, тема двух мок-клиник применяется, у клиники B подставлен наш акцент, мок-вход ведёт врача и руководителя на свои заглушки, консоль чистая, CSP не нарушен, `test_gateway.py` зелёный.

## Codex-2: FE2

1. Пока FE1 не сдал каркас — пиши экраны по контракту в своих файлах и мок-данные `PATIENT`. После коммита каркаса: `git merge rescan/fe1` в своём worktree.
2. P1 `screens/patient-entry.js`: состояния `active`, `expired`, `stopped`, `unsubscribed`, согласие при первом входе. Для `expired`, `stopped` и `unsubscribed` — что случилось и что делать дальше (позвонить в клинику, телефон клиники из мок-настроек, без кнопки «повторить»).
3. P2 `screens/patient-step.js`: если врач отметил шаг — «Ваш врач предлагает…» с текстом для `discuss`, `retest` (с числом недель) и `followup`; если нет — три ветки.
4. P3 `screens/patient-goal.js`: четыре цели из мока, выбор одной, переход на `#/p/<token>/next`.
5. Все тексты — из `texts` мока, их значения — из файлов дизайнера. В разметке строк для пациента нет.
6. Нет полей для описания самочувствия и симптомов: ни `textarea`, ни свободного ввода.
7. Без тревожных акцентов: без красных плашек, восклицаний, таймеров для пациента.
8. Всё с сервера — через `safe()`.

Готово, когда: каждое состояние P1–P3 открывается по своему мок-токену, тема клиники применяется, на 360, 390 и 1280 нет горизонтальной прокрутки, консоль чистая, проверки тестировщика по запрещённым словам зелёные.

## Дизайнер

Сдать в первые полтора часа, по порядку (от этого зависит фронтенд):

1. `docs/rescan-pilot/design/theme-system.md`: что меняет клиника (логотип, акцент, название), что остаётся нашим, правило подстановки акцента при контрасте ниже 4,5:1, как выглядит клиника без логотипа.
2. `web/pilot/css/tokens.css`: токены в `:root` на основе `web/phone.css` и `web/rescan.css` — цвета, отступы, радиусы, шрифт. Шрифт — системный стек: Stolzl коммерческий и в git не попадает.
3. `docs/rescan-pilot/design/p1-p3.md`: каркасы P1–P3 и входа сотрудника во всех состояниях из контракта (текстовые схемы блоков сверху вниз), и все тексты дословно. Тон: коротко, на «вы», «ёлочки», без канцелярита. Шаг врача — от имени врача: «Ваш врач предлагает…». Ошибки говорят, что случилось и что делать.

Потом:

4. Тексты проверить на запрещённые слова: «расшифровка», «риск», «срочно», «отклонение», «диагноз». Ни цветов, ни значков, которые оценивают результат.
5. На этапе 3 — ревью вёрстки P1–P3 и входа на 360, 390 и 1280 по скриншотам из `python start.py --web-check` или через Playwright. Правки — одним списком в `docs/rescan-pilot/design/review-18.md`: экран, ширина, что не так, как должно быть.

Готово, когда: фронтенд собрал экраны без пометок `TODO design`, список правок ревью закрыт или перенесён координатором в «Ограничения» отчёта.

## Тестировщик

1. Этап 1, сразу: `rescan_core/tests/test_b3_acceptance.py` и `rescan_core/tests/test_b4_acceptance.py` по разделу «Контракты» как чёрный ящик через HTTP. До слияния кода они красные — это ожидаемо, зафиксируй.
2. `medmarshrut_gateway_service/test_pilot_web.py` (unittest, без браузера): по всем файлам `web/pilot/` — нет запрещённых слов в текстах для пациента, нет `textarea` и полей свободного ввода на экранах пациента, нет `localStorage`, `sessionStorage`, обработчиков в разметке и внешних адресов, нет `X-Staff-Token` и строк, похожих на токены, есть плашка «демо».
3. Раздел пилота в `demo_stand/web_check.py`: P1 во всех четырёх состояниях и с согласием, P2 в трёх вариантах шага и с ветками, P3, вход врача и руководителя, неверный логин, клиника B с подставленным акцентом. Ширины 360, 390, 1280. Ошибки консоли, нарушения CSP и горизонтальная прокрутка — провал. Существующие проверки не меняй.
4. Этап 3: полный прогон раздела «Проверки» на `mvp` после всех слияний. Числа — координатору для отчёта. Красное — к владельцу файла с текстом ошибки.

Готово, когда: приёмочные тесты B3 и B4 зелёные на SQLite и PostgreSQL, проверки страниц пилота зелёные, полный прогон зелёный.

## Проверки

В `rescan_core`:

```
python -B -m pytest -p no:cacheprovider
python -B -m ruff check .
python -B -m mypy app
python -B -m alembic upgrade head
python -B -m alembic check
```

PostgreSQL: те же `pytest` с `$env:RESCAN_TEST_DATABASE_URL` на отдельную тестовую базу. Без неё тесты PostgreSQL пропускаются — так и пиши, а не «пройдено».

В корне репозитория:

```
python -B -m unittest discover -s ./medmarshrut_image_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_path_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_clinic_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_medications_service -p "test_*.py" -v
python -B -m unittest discover -s ./medmarshrut_gateway_service -p "test_*.py" -v
python start.py --smoke
python start.py --web-check
```

`--smoke` и `--web-check` поднимают стенд на портах 8763–8767. Их одновременно запускает только один исполнитель — тестировщик или координатор. Остальные гоняют только свои наборы. Не оставляй `python start.py` работать в фоне.

## Запуск Codex

PowerShell, из основной папки. Инструкция уходит в Codex через stdin, задача — аргументом. Сеть нужна для PostgreSQL на localhost, доступ к `.git` основной папки — для коммита в worktree. Пути для `--add-dir` — абсолютные.

```
Get-Content -Raw prompts\18-rescan-b3-b4-fe1-fe2.md | codex exec -C ..\jbd-b3 -s workspace-write --add-dir D:\projects_X\Just-Business-Darling\.git -c sandbox_workspace_write.network_access=true -o $env:TEMP\codex-b3.txt "Ты — Codex-1. Выполни раздел «Codex-1: B3, затем ревью B4» из инструкции ниже и соблюдай «Общие правила». Ревью B4 не начинай, пока координатор не попросит."

Get-Content -Raw prompts\18-rescan-b3-b4-fe1-fe2.md | codex exec -C ..\jbd-fe2 -s workspace-write --add-dir D:\projects_X\Just-Business-Darling\.git -o $env:TEMP\codex-fe2.txt "Ты — Codex-2. Выполни раздел «Codex-2: FE2» из инструкции ниже и соблюдай «Общие правила»."
```

Ревью B4 — отдельным запуском, когда бэкенд закончит:

```
codex exec review -C ..\jbd-b4 -o $env:TEMP\codex-review-b4.txt
```

Итог Codex читается из файла `-o`. Координатор запускает их в фоне и не ждёт активно: Claude Code сообщит, когда процесс завершится.

## Отчёт координатора

`docs/reports/18-rescan-b3-b4-fe1-fe2.md`:

- До начала: числа базового прогона.
- Что сделано по каждой задаче, кто делал.
- Как проверить: адреса мок-токенов, команды.
- Каждая правка в существующем коде — отдельной строкой: файл и зачем.
- Проверки после слияния: числа по каждому набору, SQLite и PostgreSQL отдельно.
- Ограничения и предложения команде: черновик API пациента ждёт подтверждения в B6; вход сотрудников пока моковый; планировщик истечения срока появится в B5; правки дизайнера, перенесённые на потом.
