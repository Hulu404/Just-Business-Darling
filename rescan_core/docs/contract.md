# Контракт события «анализы готовы» (зафиксирован 15.10.2026)

Единственный источник правды по полям, которые МИС отдаёт в `rescan_core`.
Фронтенд и отчёт зависят от него — менять только через ревью с командой.

## POST /v1/mis/results-ready

Заголовки:
- `X-Rescan-Signature` — hex HMAC-SHA256 с общим секретом от `timestamp.encode() + b"." + тело`
- `X-Rescan-Timestamp` — unix-время; расхождение больше `mis_signature_ttl_seconds` → 401

Тело (JSON):

| Поле | Тип | Обязательное | Что это |
|---|---|---|---|
| `event_id` | string | да | ID события в МИС, защита от дублей |
| `branch_id` | string | да | Филиал клиники |
| `patient_token` | string | да | Постоянный обезличенный ID пациента в МИС |
| `phone` | string | да | Телефон для SMS (нормализуется к цифрам) |
| `ordering_doctor_id` | string | да | Врач, назначивший анализы |
| `ready_at` | ISO-8601 datetime | да | Время готовности |
| `marketing_consent` | boolean | да | Есть ли согласие на рекламные сообщения |

Ответы:
- `202` + `{"status":"created","episode_id":"...","group":"main|control"}` — новый эпизод
- `202` + `{"status":"duplicate","event_id":"..."}` — событие уже принимали
- `401` — подпись отсутствует/неверна/протухла
- `422` — тело не соответствует контракту
- `403` — приём событий для клиники выключен
- `503` — клиника интеграции не настроена или локально найдены несколько клиник

С 17.10.2026 timestamp входит в подпись. Старые подписи только тела больше не
принимаются: обновите отправителя одновременно с сервером. Для JSON подписываются
точные отправляемые байты. Дополнительные поля JSON отклоняются; исходное тело
не сохраняется. Вне `local` и `test` обязателен `MIS_CLINIC_ID` и отдельные секреты
длиной от 32 символов. Локально без `MIS_CLINIC_ID` допустима ровно одна клиника.

## POST /v1/mis/visits-csv

Заголовки: те же; подписываются `timestamp.encode() + b"." + байты_файла`,
без multipart-заголовков и границ.
Тело: `multipart/form-data`, поле `file`.
CSV-колонки: `patient_token,visit_date,paid_amount,doctor_id`.

Ответ: `{"accepted": N, "errors": [{"line_number":..,"message":..,"raw":..}]}`.
Плохие строки не роняют загрузку — попадают в `errors`.

`accepted` — число новых визитов, сохранённых в БД. Повтор строки не увеличивает
это число. Валидные строки одного запроса записываются одной транзакцией.
Сумма задаётся в рублях: конечное неотрицательное число до 9 999 999 999,99,
не более двух знаков после запятой (разделитель в CSV — точка). В БД — копейки;
пустая сумма означает ноль. Неверная сумма попадает в ошибку строки.

`visit_date` — ISO 8601; указывайте смещение часового пояса. Для совместимости
старые значения без пояса трактуются как UTC. Ключ повтора — хэш нормализованных
`patient_token`, времени UTC, суммы в копейках и `doctor_id`, внутри клиники.
В контракте нет ID визита: одинаковые строки считаются одним визитом, а исправленная
сумма создаёт новую запись. Для полноценного обновления визитов нужен отдельный
согласованный `visit_id` от МИС.

## Группы

Группа пациента — `main` или `control`. При первом событии берём SHA-256 от
UTF-8 строки `pilot_salt:patient_token`, первые 8 hex-символов переводим в число
и берём остаток от деления на 10 000. Если число меньше `control_percent * 100`,
назначаем `control`, иначе — `main`. При одинаковых токене, соли и проценте
результат одинаковый. По умолчанию контроль — 25%; это доля на выборке, а не
точная квота. Тесты проверяют 25 ± 1% на 10 000 синтетических токенов для двух солей.

Группа фиксируется в `patients.group` внутри клиники при первом событии.
Следующее событие с новым `event_id` создаёт новый эпизод: его `group` и поле
`group` ответа берутся из сохранённой группы пациента. Смена `PILOT_SALT` или
`CONTROL_PERCENT` не пересчитывает группу уже записанного пациента и не меняет
старые эпизоды. Новые настройки применяются при первичном назначении группы.
Повтор того же `event_id` остаётся дублем и нового эпизода не создаёт.

`CONTROL_PERCENT` — целое число от 0 до 50 включительно. Вне `local` и `test`
`PILOT_SALT` обязателен: отдельный секрет длиной от 32 символов, не начинающийся
с `dev-`; пустая строка и строка из пробелов не подходят. Неверная конфигурация
останавливает запуск с ошибкой, которая называет настройку и условие, но не
печатает входные значения. В `local` и `test` разрешены демонстрационная и пустая
соль. Соль хранится только в настройках сервера и не передаётся в браузер.

## B4: очередь врача (зафиксирован 19.10.2026)

Роль `doctor` (заголовок `X-Staff-Token`). Врач сотрудника — запись `doctors`
с `external_id = actor_id` в клинике интеграции (та же, что принимает события).
Порядок проверок: токен (401) → роль (403) → клиника интеграции (503) → врач
(403, нет или неактивен) → клиника остановлена `service_enabled = false` (403)
→ список шагов клиники (503).

Статусы эпизода (`episodes.status`):

| Статус | Когда |
|---|---|
| `awaiting_doctor` | основная группа после приёма события; в очереди своего врача |
| `control` | контрольная группа; в очередь не попадает |
| `doctor_marked` | врач отметил шаг |
| `default_message` | 24 часа прошли без отметки |

`episodes.queue_deadline_at` = время приёма события (UTC) + 24 часа, только для
основной группы; у контрольной — `null`. Эпизоды до миграции остаются `open`.

Список шагов: коды фиксированы — `discuss`, `retest`, `followup`. Клиника хранит
подмножество в `clinics.step_options` (JSON-строка):

```json
[{"code": "discuss", "title": "Обсудить на приёме"},
 {"code": "retest", "title": "Пересдать через несколько недель", "weeks": [2, 4, 8, 12]}]
```

`weeks` — только у `retest`, непустой список целых от 1 до 52 без повторов.
Пусто (`null`, `""`, `[]`) или не по схеме — все три ручки отвечают `503`
`{"detail": "Список шагов клиники не настроен."}`. Значений по умолчанию нет.

### GET /v1/doctor/queue

`200` + `{"server_time": "…Z", "items": [{"episode_id", "patient_token",
"branch_name", "ready_at", "queue_deadline_at"}]}`. Только эпизоды этого врача
в `awaiting_doctor`, со сроком позже `server_time`, без отписавшихся пациентов
(`patients.opted_out`); по возрастанию `queue_deadline_at`. `branch_name` —
`branches.name`, может быть `null` (МИС передаёт только id филиала). Пусто —
`"items": []`. Телефона, ФИО и данных о здоровье нет.

### GET /v1/doctor/step-options

`200` + `{"options": [{"code", "title", "weeks"?}]}` — `weeks` только у `retest`.

### POST /v1/doctor/episodes/{episode_id}/step

Тело (`extra="forbid"`): `{"code": "retest", "retest_weeks": 4}`.

- `201` + `{"episode_id", "step_id", "status": "doctor_marked"}`.
- `404` — эпизода нет, он чужой, контрольной группы или пациент отписался.
- `409` — уже отмечен, ушёл в `default_message` или срок прошёл.
- `422` — неизвестный код, код выключен в клинике, `retest_weeks` не из списка,
  не передан для `retest` или передан (даже `null`) для другого кода, лишние поля,
  тело — массив. Ответ 422 обезличен: `{"detail": "Некорректная отметка шага.
  Проверьте поля запроса."}` для ошибок схемы, без `input` и тела запроса.
  Проверка тела идёт до поиска эпизода.

Пишет `steps` (`kind = code`, `set_by_doctor_id`, `set_at`, `due_date = set_at +
retest_weeks` для `retest`), аудит `doctor.step_marked` (actor — `actor_id`
сотрудника, payload — `step_id`, `code`, `retest_weeks`) и `outbox` с
`topic = "episode.doctor_marked"`, payload `{"episode_id", "step_id", "code",
"retest_weeks"}`. Переход — условный `UPDATE … WHERE status = 'awaiting_doctor'
AND queue_deadline_at > now`: из двух одновременных отметок или отметки и
истечения проходит ровно одна. Массовой отметки нет.

### Истечение срока

`expire_overdue(session, now) -> int` в `app/services/queue_service.py` и
`python -m scripts.expire_queue`. Эпизоды `awaiting_doctor` с
`queue_deadline_at <= now` → `default_message`, `outbox` с
`topic = "episode.default_message"`, payload `{"episode_id"}`, аудит
`queue.expired` от `system`. Возвращает число переведённых эпизодов; повтор — `0`.
`now` без пояса считается UTC. HTTP-ручки нет; планировщик — в B5.

## B6: API пациента (зафиксирован 20.10.2026)

Страница пациента по личной ссылке. Все пути — с префиксом `/v1/patient`, токен
ссылки — в заголовке `X-Patient-Link`. HTTP-выдачи ссылок нет: их выдаёт доставка (B5).

### Ссылка

Таблица `patient_links`: `id`, `episode_id`, `token_hash` (уникальный), `expires_at`,
`revoked_at`, `created_at`. Токен — `secrets.token_urlsafe(32)`, в базе только
`HMAC-SHA256(patient_link_secret, токен)` в hex (`app/security/patient_link.py`).
`issue_link(session, episode_id, now)` в `app/services/patient_service.py` возвращает токен
один раз; эпизоду контрольной группы и несуществующему ссылка не выдаётся (`LookupError`).
Демо: `python -m scripts.issue_link <episode_id> [--base-url http://127.0.0.1:8763]`
печатает `…/assets/pilot/index.html#/p/<токен>`.

Настройки: `PATIENT_LINK_SECRET` (вне `local` и `test` — от 32 символов, без префикса
`dev-`), `PATIENT_LINK_TTL_DAYS` — от 1 до 90, по умолчанию 30.

Нет заголовка, токен не `[A-Za-z0-9_-]{16,128}`, хэша нет в базе, ссылка отозвана, эпизод
контрольной группы — одинаковый ответ `404 link_not_found`.

### Настройки клиники

`clinics.patient_settings` — JSON-строка:

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

Обязательны `timezone` (имя пояса IANA), непустые `branches` и `windows` без повторов `code`
(`code` ветки — до 16 символов, окна — до 64) и объект `texts` со строками. Пусто, не JSON
или не по схеме — `503 not_configured` на всех путях. Значений по умолчанию нет.
`phone` и `privacy_url` необязательны; `privacy_url` и `payment_url` отдаются только
`https://`, иначе `null`. Тема — `clinics.theme` с ключами `name`, `logo_url`, `accent`;
старые ключи `logo` и `title` переименовала миграция `20261020_patient_api`, ответ их не читает.

Врачи цели — таблица `goal_doctors` (`goal_id`, `doctor_id`, `sort_order`, первичный ключ —
пара). Выбор пациента — `episodes.chosen_branch` и `episodes.chosen_goal_id`.

### Порядок проверок и ошибки

Ссылка (404) → тело по схеме (422) → настройки клиники (503) → состояние (409
`not_active`, кроме `GET /session`) → согласие (409 `consent_required`, кроме
`GET /session` и `POST /consent`) → выбор цели (409 `choice_required` для `doctors`,
`formats`, `requests`) → значения из списков (422). Исключение: тело, которое не
разбирается как JSON, получает 422 раньше проверки ссылки.

| Код | `code` | Когда |
|---|---|---|
| 404 | `link_not_found` | см. «Ссылка» |
| 409 | `not_active` | `state` не `active` |
| 409 | `consent_required` | нет согласия `pd_processing` |
| 409 | `choice_required` | цель не выбрана |
| 409 | `request_exists` | у эпизода есть заявка в `new`, `sent` или `in_progress` |
| 422 | `invalid_input` | тело не по схеме, лишние поля, значение не из списка |
| 503 | `not_configured` | настройки клиники неполные |

Тело ошибки: `{"detail": {"code": "…", "message": "…"}}`, `message` по-русски.
Ответ 422 обезличен: тело запроса и `input` в него не попадают.

### GET /v1/patient/session

`state`: `unsubscribed` (`patients.opted_out`) → `stopped` (`clinics.service_enabled =
false`) → `expired` (`expires_at <= now`) → `active`, проверяются в этом порядке.
Не `active` — в ответе только `state`, `clinic` и `texts`. `active`:

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

- `doctor_step` — последний шаг эпизода с `set_by_doctor_id`, иначе `null`. Для `retest`:
  `retest_weeks` = (`due_date` − `set_at`) в неделях, `due_date` — дата в поясе клиники,
  `retest_state` — `before`, `today` или `overdue` по сегодняшней дате в поясе клиники.
  Для других кодов эти три поля `null`.
- `goals` — активные цели клиники по `sort_order`. `choice` — `null`, пока цель не выбрана.
- `request` — последняя заявка в `new`, `sent`, `in_progress`, иначе последняя в `booked`
  или `cancelled`, иначе `null`. Статус для пациента: `new`, `sent` → `accepted`, остальные
  как есть. `window_title` — `null`, если окна больше нет в настройках.
- `consent_required` — нет записи `consents` с `kind = pd_processing`, `granted = true`.
- Телефона пациента, `patient_token`, групп и данных о здоровье в ответе нет.

### POST /v1/patient/consent

Без тела → `200 {"ok": true}`. Пишет `consents` (`pd_processing`, `granted`,
`source = link`) и аудит `patient.consent` (`entity_id` — эпизод, без payload). Повтор
ничего не пишет.

### POST /v1/patient/choice

`{"branch_code": "discuss" | null, "goal_id": "…"}`, `extra="forbid"` → `200 {"ok": true}`.
Врач отметил шаг — `branch_code` только `null` (или не передан); не отметил — обязателен и
из `branches`. `goal_id` — активная цель клиники пациента. Иначе 422. Повтор перезаписывает.

### GET /v1/patient/doctors

`{"doctors": [{"id", "name", "specialty", "photo_url", "tag"}]}` для выбранной цели:

1. Врач, назначивший анализы (`episodes.ordering_doctor_id`), если активен — `"ordering"`.
2. Врачи цели, у которых пациент уже был (`visits` по `patient_token` и
   `doctor_external_id` в этой клинике), сначала последний визит — `"visited"`.
3. Остальные врачи цели по `sort_order` — `null`.

Без повторов, только активные врачи этой клиники. Нет врачей — `{"doctors": []}`.

### GET /v1/patient/formats

`{"formats": [{"id", "title", "price_kopecks", "currency", "has_payment"}], "windows":
[{"code", "title"}]}` — активные форматы клиники; `has_payment` — у формата `https://`
адрес оплаты. Сам адрес здесь не отдаётся.

### POST /v1/patient/requests

`{"doctor_id", "format_id", "window_code"}`, `extra="forbid"` → `201 {"request_id",
"status": "accepted", "payment_url": "https://…" | null}`.

- Врач — из `GET /doctors` для выбранной цели, формат активный, окно из `windows`, иначе 422.
- Создаёт `requests` (`status = new`, `goal_id` из выбора, `window = window_code`), `outbox`
  с `topic = crm` и `payload = {"request_id"}`, аудит `patient.request_created`
  (payload `{"request_id"}`). Телефона нет ни в `outbox`, ни в аудите.
- Одна незавершённая заявка на эпизод: перед проверкой строка эпизода блокируется условным
  `UPDATE`, из двух одновременных запросов проходит один, второй получает 409.

## B7: заявки в CRM (20.10.2026)

### Настройки и запуск

`CRM_TARGETS` — JSON-объект `{clinic_id: {kind, url, secret}}`, где `kind` —
`bitrix24` или `webhook`. Для `webhook` секрет обязателен. `NOTIFY_TARGETS` —
JSON-объект `{clinic_id: {url, secret}}` запасного канала администратора.
Адреса и секреты читаются из окружения, не записываются в БД, аудит и логи.
В production адреса только HTTPS, секреты от 32 символов без префикса `dev-`.
У Битрикс24 отдельный `secret` необязателен (авторизация в адресе вебхука);
если он задан, требования к секрету такие же. В `local`/`test` дополнительно
разрешён HTTP строго на `127.0.0.1`. Redirect, URL с userinfo и fragment запрещены.

`CRM_STATUS_SECRET` — отдельный секрет входящего статуса; в production обязателен,
от 32 символов, без `dev-`. В local/test есть демонстрационное значение.
Ошибки конфигурации не показывают переданные значения.

Запуск из `rescan_core`: `python -m scripts.deliver_crm`. Скрипт вызывает
`deliver_pending(session, now, send=http_send) -> int` и фиксирует транзакцию.
`http_send(kind, target, payload)` из `app/services/crm_transports.py` — отправка
по умолчанию; тесты передают свою функцию или поднимают фейковый приёмник. Возвращается
число обработанных записей очереди, включая запасные уведомления. Функция сама
не делает commit: вызывающий обязан завершить транзакцию. Планировщик — B5.
`now` без пояса трактуется как UTC.

### Доставка

Обрабатываются `outbox` с `topic = crm` или `notify`, `status = pending` и
`available_at IS NULL` или `available_at <= now`. Условный `UPDATE ... WHERE
status = pending` забирает запись, блокировка удерживается до конца транзакции,
включая HTTP-вызов. Два обработчика одной записи не отправляют её одновременно.

`payload` очереди — только `{"request_id": "…"}`. Данные заявки и контакт читаются
в момент отправки; телефон расшифровывается только для тела исходящего запроса.
Выбранные врач, формат и цель должны принадлежать клинике пациента.

Битрикс24: `POST <url>/crm.lead.add.json`, JSON с объектом `fields`:

- `TITLE`: «Заявка rescan: <цель>»;
- `PHONE`: `[{"VALUE": "…", "VALUE_TYPE": "MOBILE"}]`;
- `COMMENTS`: врач, формат и окно времени;
- `SOURCE_DESCRIPTION`: `rescan`.

Успех — 2xx и непустой `result` (строка или целое, до 128 символов), записывается
в `requests.crm_request_id`.

Универсальный вебхук: `POST <url>`, JSON:

```json
{"request_id":"…","clinic_id":"…","patient_token":"…","phone":"…",
 "doctor":{"external_id":"…","name":"…"},
 "format":{"title":"…","price_kopecks":100000},
 "window":{"code":"morning","title":"…"},
 "goal":{"title":"…"},"created_at":"2026-10-20T10:00:00+00:00"}
```

`X-Rescan-Timestamp` — unix-время, `X-Rescan-Signature` — hex HMAC-SHA256
от `timestamp.encode() + b"." + точные_байты_тела` с секретом канала, как у МИС.
Любой 2xx — успех; необязательный `crm_request_id` сохраняется, если это строка
или целое длиной до 128 символов. Тело ответа не сохраняется и не логируется.
Тайм-аут — 10 секунд; перенаправления не выполняются.

Успех: `requests.status` из `new` в `sent`, очередь в `done`, `processed_at`,
аудит `crm.request_sent`. Более поздний статус заявки не откатывается.
Неудача: `attempts + 1`, интервалы до следующей попытки 1, 5, 15, 60 минут.
Пятая неудача: `failed`, `processed_at`, аудит `crm.request_failed`, новая
запись `notify` с одним `request_id`. Нет CRM — сразу `notify`, исходная задача
завершается. Новое уведомление может быть обработано тем же вызовом функции.

Тело `notify`: `{request_id, clinic_id, phone, doctor, format, window, goal, reason}`.
Подпись такая же; `reason` — `crm_failed` или `no_crm`. В очереди причина не
хранится: `crm_failed` определяется по аудиту неудачной CRM-доставки этой заявки.
Успешное уведомление статус заявки не меняет: она остаётся `new`, очередь
`notify` — `done`, аудит `crm.notify_sent` с payload `{"reason": …}`.
Повторы уведомления — по тому же расписанию, максимум пять попыток. Нет запасного
канала или его попытки исчерпаны — `failed`, аудит `crm.no_channel`, сообщение
в лог без идентификаторов пациента, телефона, URL и текста исключения.

Отписавшемуся пациенту ничего не отправляется: незавершённая заявка `cancelled`,
очередь `done`, аудит `crm.skipped_opted_out`. Заявки с конечным статусом
`booked`/`cancelled` повторно не отправляются и не изменяются.

### POST /v1/crm/status

Подпись и timestamp обязательны, схема как у МИС, секрет — `CRM_STATUS_SECRET`.
Допустимое отклонение времени — `MIS_SIGNATURE_TTL_SECONDS` (по умолчанию 300).
Тело строгое (`extra=forbid`): один из `request_id` или `crm_request_id`,
плюс `status`: `in_progress`, `booked` или `cancelled`. Оба идентификатора,
явный null, пустой идентификатор, неизвестные поля и статусы не принимаются.

- 200: `{"request_id": "…", "status": "…"}`; повтор того же статуса — без нового аудита.
- 401 `bad_signature`: подпись отсутствует, неверна, устарела или timestamp некорректен.
- 404 `request_not_found`: заявка не найдена; неоднозначный внешний ID также не выбирается наугад.
- 409 `invalid_transition`: недопустимый переход или конкурентное изменение.
- 422 `invalid_input`: тело не по схеме, без возврата исходных значений.

Ошибки — в формате B6: `{"detail": {"code": "…", "message": "…"}}`.

Переходы: `new → sent → in_progress → booked`, вперёд можно через шаг
(после `notify` заявка остаётся `new`, администратор записывает пациента сам);
`sent` устанавливает только доставка. Из `new`, `sent`, `in_progress` допустим
`cancelled`. `booked` и `cancelled` конечные. Аудит `crm.status_changed`, actor и role — `crm`,
payload содержит только прежний и новый статусы.

### POST /v1/admin/requests/{request_id}/status

`X-Staff-Token`, только роль `administrator`. Тело `{"status": "…"}`, те же
переходы, 200/404/409/422 с теми же кодами ошибок. Нет служебного токена — 401,
другая роль — 403 (формат ролей B1).
Доступ только к клинике из `MIS_CLINIC_ID`; чужая заявка — 404. Аудит
`crm.status_changed` с `actor_id` сотрудника и ролью `administrator`.

### Ограничения B7

- Исходящие вебхуки Битрикс24 (форма и ID лида) напрямую не принимаются.
  Клиника настраивает робота, который отправляет подписанный JSON на `/v1/crm/status`.
- Защита захвата очереди предотвращает одновременную отправку одной записи.
  Потеря ответа после успешного приёма или падение процесса до commit могут
  вызвать повтор. Универсальный приёмник должен дедуплицировать `request_id`;
  для Битрикс24 это отдельная задача интеграции.
- `requests.window` хранит код окна. Подпись берётся из `windows` в
  `clinics.patient_settings` (колонка B6). Нет колонки, настройки пусты, не JSON
  или окна с таким кодом нет — `window = {code, title: null}`, доставка не падает;
  в комментарии Битрикс24 тогда стоит код. Подписи окон не выдумываются.
- Внешние ID CRM могут совпадать у разных клиник. При неоднозначности следует
  передавать внутренний `request_id`; автоматического выбора первой заявки нет.
