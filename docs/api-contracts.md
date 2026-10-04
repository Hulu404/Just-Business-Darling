# Контракты сервисов: шпаргалка

Сверено с кодом на коммите `4dedd5d` (ветка `develop`, 4 октября 2026). Источник истины — код. Видишь расхождение — верь коду и поправь этот файл.

## Общее для трёх сервисов

- Python, стандартный `http.server`, слушают только `127.0.0.1`. CORS-заголовков нет: браузер с другого origin к ним не достучится.
- Тела и ответы — JSON в UTF-8. Ошибка выглядит как `{"error": "текст на английском"}`.
- Коды ошибок непоследовательны, по одному коду причину не определить: читай текст. 403 — нет токена, неверная подпись, а в сервисе клиники ещё регистрация пациента и запись анамнеза в чужую клинику. 400 — неверный формат, а ещё «объект не найден» в большинстве `POST` и «не та роль» в сервисе клиники. 409 — конфликт состояния, а в сервисе клиники ещё и действие с направлением или статусом от имени чужой клиники. 404 приходит на `GET`, на неизвестный путь и на `POST /v1/referrals` с незнакомым `patient_ref`. Сервис снимков 409 не возвращает вообще: повторное подтверждение — 400.
- Обработчики сравнивают набор ключей тела с ожидаемым (`set(body) != {...}`). Лишний или пропущенный ключ даёт 400. Где поле может быть пустым, оно передаётся явно как `null`; какие поля допускают `null`, сказано у каждого запроса.
- Время — ISO 8601 с часовым поясом. Без пояса запрос отклоняется.
- Проверка типов неполная. Значение неожиданного типа (список вместо строки, `null` там, где его не ждут) в ряде мест роняет обработчик: соединение закрывается без ответа. Вызывающая сторона сама проверяет типы и длины и считает обрыв соединения ошибкой сервиса.
- Лимиты тела считаются в байтах. Кириллица в `json.dumps` по умолчанию занимает шесть байт на букву (`\uXXXX`): сериализуй с `ensure_ascii=False`, тогда две.
- Идентификаторы в путях не декодируются из URL-кодировки. `patient_ref` с двоеточием, записанным как `%3A`, не найдётся: используй в псевдонимах только буквы, цифры, дефис, точку и подчёркивание.

### Подпись между сервисами

Одинаковая в `medmarshrut_path_service/auth.py`, `medmarshrut_clinic_service/auth.py` и в отправке из сервиса снимков.

```
X-Path-Timestamp: <unix-время в секундах, 10–12 цифр>
X-Path-Signature: sha256=<hex HMAC-SHA256(секрет, timestamp + "." + сырое_тело)>
```

Допуск по времени ±300 секунд. Подписывай ровно те байты, которые отправляешь: сначала сериализуй JSON, потом считай подпись по этим байтам. Для `GET` без тела подписывается пустая строка байт, то есть `timestamp + "."`.

---

## Сервис снимков — `medmarshrut_image_service`, порт 8766

Переменные окружения: `REVIEWER_TOKEN` (обязательна), `MODEL_CONFIG` (путь к `model.json`) или `ENABLE_TEST_BACKEND=1`, `ROUTER_URL` (строго `http://127.0.0.1:<порт>/v1/reports`), `PATH_SHARED_SECRET` (обязательна, если задан `ROUTER_URL`).

Задания и архивы лежат в памяти процесса и пропадают при перезапуске. Списка исследований в API нет: идентификатор нужно помнить самому.

| Запрос | Доступ | Тело | Ответ |
|---|---|---|---|
| `GET /health` | — | — | `{"status":"ok"}` |
| `POST /v1/studies` | — | `application/zip` до 50 МиБ, заголовок `X-Study-Manifest` (JSON до 64 КиБ) | публичный статус, коды ниже |
| `GET /v1/studies/{id}` | — | — | публичный статус |
| `GET /v1/review/{id}` | `Bearer REVIEWER_TOKEN` | — | полное задание |
| `GET /v1/review/{id}/images/{sop_uid}` | `Bearer REVIEWER_TOKEN` | — | исходный DICOM, `application/dicom` |
| `POST /v1/review/{id}` | `Bearer REVIEWER_TOKEN` | JSON до 8192 байт | полное задание |

Манифест: `{"task": "...", "study_uid": "1.2.3", "series": {"<series_uid>": ["<sop_uid>", ...]}}`. В нём перечислен каждый ожидаемый срез или проекция. Архив с другим набором UID отклоняется.

Задачи (`task`): `ct_general` (КТ, не меньше двух срезов), `mr_general` (МРТ, не меньше двух срезов), `mg_screening_2d` (маммография, ровно четыре проекции: L-CC, L-MLO, R-CC, R-MLO, только `FOR PRESENTATION`).

Требования к DICOM: Part 10; SOP-класс CT Image Storage, MR Image Storage или Digital Mammography X-Ray Image Storage — For Presentation; несжатый little endian (`1.2.840.10008.1.2` или `1.2.840.10008.1.2.1`); `ImageType` начинается с `ORIGINAL`, `PRIMARY`; один кадр; `MONOCHROME1` или `MONOCHROME2`; 8 или 16 бит; есть `PixelSpacing`. Для КТ и МРТ нужны ориентация, позиция, `InstanceNumber` и ровный шаг срезов, для КТ ещё `RescaleSlope` и `RescaleIntercept`. В архиве одно исследование, один `ProtocolName` и один `BodyPartExamined`. Лимиты: 512 файлов, 32 серии, 40 МиБ на файл, 200 МиБ после распаковки.

Публичный статус: `{"id", "created_at", "status", "reason", "routing_status"}`. Черновика и находок в нём нет, но `reason` может выдать результат модели: `No supported finding above threshold` означает, что модель ничего не нашла. Пациенту и координатору причину показывать нельзя.

Коды ответа `POST /v1/studies` (тело во всех случаях, кроме 413 и 415, — публичный статус, задание создано):

| Код | Когда |
|---|---|
| 201 | `awaiting_physician` или `test_only` |
| 202 | `manual_review`, потому что модель не подключена |
| 422 | `manual_review` по любой другой причине: архив не прошёл проверку, протокол не подходит модели, модель отказалась, находок выше порога нет |
| 503 | сбой инференса, загрузки модели или нехватка памяти |
| 504 | тайм-аут инференса |
| 413, 415 | размер или тип тела, задание не создано |

При 413 и 415 сервис отвечает, не читая тело, и закрывает соединение. Клиент с большим телом может увидеть обрыв записи вместо кода. Тип и размер архива проверяет вызывающая сторона до отправки.

Статусы задания: `processing` (только внутри вызова), `manual_review`, `test_only` (тестовый backend, подтвердить нельзя), `awaiting_physician`, `confirmed`.

Полное задание: `{"id", "created_at", "status", "reason", "study", "result", "draft", "edits", "confirmation", "routing_status"}`.

- `study`: `{"task", "modality", "study_uid", "protocol_name", "anatomy", "instance_count", "series": {...}}` или `null`, если архив не прошёл проверку. `anatomy` — это `BodyPartExamined` в верхнем регистре, `protocol_name` — `ProtocolName` как в файле. Серия КТ и МРТ: `instance_count`, `rows`, `columns`, `pixel_spacing_mm`, `slice_spacing_mm`, `ordered_sop_uids`. Серия маммографии: `views`, `projections` (`sop_uid` → `"L-CC"`).
- `result`: `{"kind": "model_inference", "backend", "model_version", "input_quality", "limitations": [...], "findings": [...], "refusal_reason", ...}`. Находка: `{"code", "description", "confidence", "localization": {"series_uid", "sop_uid", "slice_index" | "projection"}}`. Локализация — номер среза или проекция. Координат области модель не возвращает.
- `draft`: `[{"finding_id", "text"}]`, по строке на находку. Текст строки собирает сервис: «Модель предполагает: <описание> (срез N, серия <UID>, экземпляр <UID>; оценка 0.91). Требуется проверка врача.» В нём есть оценка модели и UID: в заключение для пациента этот текст без правки не годится.
- `result` равен `null`, если инференса не было: модель не подключена, архив не прошёл проверку, протокол не подходит. У тестового backend `result` — `{"kind": "test_only", "backend", "message"}` без `findings`. При отказе модели и при отсутствии находок `findings` и `draft` пусты.
- Изображения отдаются для любого задания, архив которого прошёл проверку, в любом статусе.

Подтверждение, `POST /v1/review/{id}`: `{"physician_id", "conclusion", "edits": ["..."], "finding_code"}` и необязательный `"patient_ref"`. Условия: статус `awaiting_physician`; `finding_code` — один из кодов в `result.findings`; `physician_id` 1–128 символов; `conclusion` 1–4000; каждая правка до 1000; `patient_ref` по шаблону `[A-Za-z0-9_.:-]{2,128}`. Всё тело — не больше 8192 байт: заключение на 4000 кириллических символов занимает 8000 байт даже с `ensure_ascii=False`, поэтому на практике текст нужно держать заметно короче. Тело больше лимита получает 400 с пустым текстом ошибки.

После подтверждения сервис сам отправляет подписанное заключение на `ROUTER_URL`. `routing_status`: `pending` → `sent` или `failed`; без `ROUTER_URL` — `not_configured_or_unsupported`. Повторной отправки нет. Ответ сервиса пути не сохраняется, поэтому `episode_id` в задании не появляется: эпизод ищут в сервисе пути по `source_report_id`, равному идентификатору задания. Соответствие модальности и `study_type`: `CT` → `ct`, `MR` → `mr`, `MG` → `mammography`.

---

## Сервис пути — `medmarshrut_path_service`, порт 8765

Переменные окружения: `PATH_SHARED_SECRET` и `PATH_ADMIN_TOKEN` (каждая не короче 16 символов), `PATH_DB` (по умолчанию `path.sqlite3` рядом с сервисом), `PATH_RULES` (по умолчанию `rules.json` рядом с сервисом), `PATH_PATIENT_TOKEN`, `PATH_MIS_TOKEN` (пусто — роль выключена).

Тело `POST` до 16 КиБ, `Content-Type: application/json` обязателен.

| Запрос | Доступ | Тело | Ответ |
|---|---|---|---|
| `GET /health` | — | — | `{"status":"ok"}` |
| `POST /v1/reports` (синоним `POST /v1/episodes`) | подпись, `PATH_SHARED_SECRET` | заключение, 15 полей | 201 `{"episode_id", "status", "manual_reason", "duplicate": false}`; точный повтор — 200 и `"duplicate": true`; тот же ключ с другим содержимым — 409 |
| `GET /v1/episodes` | админ | — | `{"episode_ids": [...]}`, до 100 последних, без фильтров и страниц |
| `GET /v1/episodes/{id}` | админ | — | эпизод |
| `POST /v1/episodes/{id}/manual-plan` | админ | `{"actor", "steps": [{"kind", "description"}]}` | эпизод |
| `POST /v1/episodes/{id}/steps/{step_id}` | админ | `{"actor", "evidence"}` | эпизод; закрывает только шаг вида `care_coordination` |
| `POST /v1/episodes/{id}/steps/{step_id}/{действие}` | админ | `{"actor", "evidence"}` плюс `"appointment_at"`, `"due_at"` | эпизод |
| `POST /v1/episodes/{id}/revise-plan` | админ | `{"physician_id", "reason", "steps": [...]}` | эпизод |
| `POST /v1/episodes/{id}/stop` | админ | `{"actor", "reason"}` | эпизод |
| `POST /v1/episodes/{id}/close` | админ | `{"actor", "outcome"}` | эпизод |
| `POST /v1/episodes/{id}/outcomes` | админ для `staff_form`, `PATH_MIS_TOKEN` для `mis` | `{"step_id", "outcome": {...}}` | `{"episode": {...}, "duplicate": bool}` |
| `GET /v1/staff/queue` | админ | — | `{"cases": [...]}` |
| `GET /v1/staff/metrics` | админ | — | показатели |
| `GET /v1/rules` | админ | — | `{"version", "supported_protocols", "rules"}` из загруженного файла |
| `POST /v1/rules/dry-run` | админ | `{"study_type", "anatomy", "protocol_name", "finding_code"}` | `{"dry_run": true, "steps": [...], "manual_reason", "rule_version"}`; ничего не записывает |
| `GET /v1/staff/outbox` | админ | — | `{"events": [...]}` |
| `GET /v1/patient/{patient_ref}` | токен пациента | — | `{"episodes": [...]}` |
| `GET /patient`, `GET /staff` | — | — | встроенные HTML-страницы, токен вводится на странице |

«Админ» — `Authorization: Bearer <PATH_ADMIN_TOKEN>`. Токен пациента — `Bearer` + hex HMAC-SHA256 от `patient_ref` с ключом `PATH_PATIENT_TOKEN`.

### Заключение (`POST /v1/reports`)

Ровно эти поля: `source_service` (только `medmarshrut_image_service`), `source_report_id`, `source_report_version` (целое от 1), `confirmation_status` (только `confirmed`), `physician_id`, `confirmed_at`, `study_type`, `study_uid`, `patient_ref` (строка до 128 или `null`), `anatomy`, `protocol_name`, `finding_code`, `conclusion` (до 4000), `confidence` (0–1 или `null`), `source_model`.

Новая версия того же заключения создаёт отдельный эпизод с причиной `report_revision`. `study_type` при приёме не сверяется со списком: неизвестный тип проходит проверку и уходит на ручной разбор как `unsupported_protocol`.

### Эпизод и шаги

Эпизод: `{"id", "status", "source_report": {...}, "plan_steps": [...], "audit_events": [...], "rule_version", "manual_reason", "created_at", "updated_at", "closed_at"}`.

Шаг: `{"id", "episode_id", "position", "kind", "description", "status", "completed_at", "owner", "due_at", "continue_on", "decision_source", "cycle", "appointment_at", "stop_reason"}`.

Событие журнала: `{"id", "episode_id", "event_type", "actor", "occurred_at", "details"}`.

- Статусы эпизода: `active`, `manual_review`, `paused`, `completed` (после `close`), `closed` (после `stop`).
- Виды шагов: `appointment`, `test`, `follow_up`, `care_coordination`; `manual_review` создаёт только сам сервис.
- Статусы шага: `open` → `offered` → `confirmed` → `attended` → `completed`. Боковые: `cancelled`, `refused`, `lost_contact` (эпизод уходит в `paused`), `superseded` (после `revise-plan`), `closed` (после `stop`).

| Действие | Из каких статусов | Что нужно |
|---|---|---|
| `offer` | `open` | `appointment_at`; все шаги с меньшей позицией `completed` или `superseded` |
| `confirm` | `offered` | — |
| `attend` | `confirmed` | — |
| `cancel`, `refuse` | `offered`, `confirmed` | — |
| `lost_contact` | `open`, `offered`, `confirmed` | — |

Переходы работают только в эпизоде со статусом `active` и не применяются к шагу `manual_review`. Клинический шаг завершается только итогом визита (`outcomes`) и только из статуса `attended`.

Три вещи про переходы, которых нет в README сервиса:

- «Завершены» в условии `offer` значит `completed` или `superseded` (исправлено в задании 01; на коммите `4dedd5d` шаг `superseded` блокировал `offer` нового шага после `revise-plan`, ответ был 409 `Earlier plan step is unfinished`).
- `appointment_at` и `due_at` принимает любой переход, и новое значение заменяет прежнее. `confirm` с другим `appointment_at` подтверждает запись сразу на новое время. Для шага в статусе `confirmed` сменить время нечем: остаются `attend`, `cancel` и `refuse`.
- `manual-plan` переводит эпизод в `active`, но не очищает `manual_reason`; `revise-plan` очищает. Ручной разбор определяй по `status`, а не по непустой причине.

Итог визита: `{"source": "mis" | "staff_form", "event_id", "physician_id", "confirmed_at", "summary", "next_steps": [...]}`. Каждый следующий шаг — ровно пять ключей: `kind`, `description`, `owner`, `due_at` (время или `null`), `continue_on`. Пара `(source, event_id)` идемпотентна: точный повтор вернёт `"duplicate": true`, тот же `event_id` с другим содержимым — 409. Сравнивается весь объект `outcome`, включая `confirmed_at`: повтор с новой отметкой времени считается другим содержимым. `step_id` в сравнение не входит. Пустой `next_steps` завершает план, закрывает эпизод сотрудник.

`owner` и `continue_on` — свободные строки до 500 символов. Значения, которые сервис ставит сам: `owner: "coordinator"`, `continue_on: "confirmed_outcome"`.

`manual-plan` работает только в статусе `manual_review`, принимает 1–50 шагов. `revise-plan` работает в `active` и `paused`, шаги в том же формате из пяти ключей; незавершённые шаги становятся `superseded`. `close` требует, чтобы все шаги были `completed` или `superseded`.

Значения `manual_reason`: `missing_patient_ref`, `unsupported_protocol`, `unknown_finding_code`, `no_approved_rule`, `rule_not_approved`, `report_revision`. У эпизода на паузе — `cancel`, `refuse`, `lost_contact`. После `stop` — текст причины.

Значения `decision_source`: `rule:<версия>`, `source_report` (шаг ручного разбора), `physician:<actor>` (ручной план), `<source>:<event_id>:physician:<physician_id>` (итог визита), `physician_revision:<physician_id>`.

События журнала: `episode_created`, `manual_plan_approved`, `step_completed`, `step_offered`, `step_confirmed`, `step_attended`, `step_cancelled`, `step_refused`, `step_lost_contact`, `outcome_confirmed`, `plan_revised`, `episode_completed`, `episode_closed`.

События `outbox`: `episode_created`, `plan_updated`, `episode_closed`, `step_offered`, `step_confirmed`, `step_attended`, `step_cancelled`, `step_refused`, `step_lost_contact`. Формат: `{"id", "episode_id", "event_type", "payload", "created_at"}`, `id` растёт. `patient_ref` в событии нет, его берут из эпизода. Сам сервис ничего пациентам не отправляет.

Очередь: `{"episode_id", "status", "reasons": [...], "actions": [...]}`. Причины: `manual_reason` или статус для `manual_review` и `paused`, `awaiting_confirmed_outcome`, `unfinished:<step_id>`, `overdue:<step_id>` (считается при чтении по `due_at`). Действия: `request_physician_plan` для неактивного эпизода, иначе `contact_owner_or_record_outcome`.

Показатели: `contact_seconds_average`, `offered_share`, `confirmed_share_of_offered`, `attended_visits`, `unfinished_episodes`, `manual_correction_share`, `route_quality: {"episodes_requiring_route_review", "share_requiring_route_review"}`. Пока данных нет, доли равны `null`.

Вид пациента: `{"episode_id", "status", "do_now": {"description", "status", "appointment_at"} | null, "plan_history": [{"description", "status", "cycle", "appointment_at"}]}`. В нём нет идентификаторов и видов шагов, а шаг ручного разбора приходит с техническим текстом `Review source report: <причина>`.

### Правила (`rules.json`)

```json
{
  "version": "clinic-rules-v1",
  "supported_protocols": [{"study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN"}],
  "rules": [{"study_type": "mr", "anatomy": "BRAIN", "protocol_name": "MR_BRAIN",
             "finding_code": "FINDING_X", "approved": true,
             "steps": [{"kind": "appointment", "description": "..."}]}]
}
```

Правило срабатывает при точном совпадении четырёх полей и `"approved": true`. `study_type` — только `ct`, `mr`, `mammography`. Шаг правила — ровно `kind` и `description` (до 500 символов), срок пишется словами в описании. Файл читается при старте сервиса. Поставляемый `rules.json` пуст намеренно: без правил клиники каждое заключение уходит на ручной разбор. Эндпоинта для чтения правил нет.

Проверка файла пропускает шаг вида `manual_review` в правиле, но такой шаг нельзя ни предложить, ни завершить. В правилах его не используй.

---

## Сервис клиники — `medmarshrut_clinic_service`, порт 8764

Переменные окружения: `CLINIC_SHARED_SECRET` и `CLINIC_ADMIN_TOKEN` (каждая не короче 16 символов), `CLINIC_STAFF_TOKENS` (JSON-объект «токен → `clinic_id`»), `CLINIC_DB` (по умолчанию `clinic.sqlite3` рядом с сервисом), `CLINIC_NETWORK` (по умолчанию `network.json` рядом с сервисом), `CLINIC_MIS_TOKEN`.

Тело `POST` до 32 КиБ, `Content-Type: application/json` обязателен. Токен сотрудника задаёт клинику: сотрудник действует только от её имени.

| Запрос | Доступ | Тело | Ответ |
|---|---|---|---|
| `GET /health` | — | — | `{"status":"ok", "network_version"}` |
| `POST /v1/route-candidates` | подпись, `CLINIC_SHARED_SECRET` | `{"patient_ref", "scope": {"study_type", "anatomy", "protocol_name", "finding_code"}}` | кандидаты |
| `POST /v1/referrals` | подпись | `{"patient_ref", "from_clinic_id", "to_clinic_id", "reason", "created_by"}` | 201, направление |
| `GET /v1/patients/by-ref/{patient_ref}` | подпись по пустому телу | — | `{"patient_ref", "home_clinic_id", "home_clinic_name", "status"}` |
| `POST /v1/patients` | сотрудник своей клиники или МИС | `{"home_clinic_id", "patient_ref", "full_name", "birth_date", "sex", "contact"}` | 201, `{"patient": {...}}` |
| `POST /v1/patients/{id}/anamnesis` | сотрудник домашней клиники или МИС | `{"kind", "code", "text", "shareable", "recorded_at", "author_id", "author_role", "clinic_id"}` | 201, `{"entry": {...}}` |
| `POST /v1/patients/{id}/status` | сотрудник домашней клиники | `{"status", "actor"}` | `{"patient": {...}}` |
| `POST /v1/referrals/{id}/{accept\|reject\|cancel\|complete}` | сотрудник | `{"actor"}` и необязательный `"note"` | направление |
| `GET /v1/clinics` | сотрудник или админ | — | `{"clinics": [...], "network_version"}`; сотрудник видит свою клинику и партнёров |
| `GET /v1/partnerships` | сотрудник | — | `{"partners": ["clinic_id", ...]}` |
| `GET /v1/patients?status=&limit=` | сотрудник (своя клиника) или админ | — | `{"patients": [...]}`; неверные `limit` или `status` — 400 (с задания 06) |
| `GET /v1/referrals?status=` | сотрудник | — | `{"referrals": [...]}`: направления, где клиника сотрудника — отправитель или получатель; к каждому добавлен `patient_ref` (с задания 06) |
| `GET /v1/patients/{id}`, `GET /v1/patients/{id}/card` | сотрудник или админ с `?clinic_id=` | — | карта, оба пути отвечают одинаково |
| `GET /v1/staff/queue` | сотрудник | — | `{"cases": [...]}` |
| `GET /v1/staff/metrics` | сотрудник | — | показатели клиники |
| `GET /staff` | — | — | встроенная HTML-страница |

В путях сотрудника стоит внутренний `id` пациента, в подписанных запросах — `patient_ref`. Чтобы получить `id` по псевдониму, найди пациента в `GET /v1/patients`.

Пациент: `{"id", "home_clinic_id", "patient_ref", "full_name", "birth_date", "sex", "contact", "status", "created_at", "updated_at"}`. `patient_ref` — `[A-Za-z0-9_.:-]{2,128}`, уникален. `sex` — `M`, `F`, `X` или `null`. `birth_date` — дата ISO или `null`. Статусы: `active`, `archived`, `transferred`, `deceased`.

`author_id` обязателен и не может быть `null`: иначе обработчик падает без ответа.

Запись анамнеза: `kind` из `diagnosis`, `allergy`, `medication`, `surgery`, `family_history`, `risk_factor`, `note`, `measurement`, `lab`; `author_role` из `physician`, `coordinator`, `nurse`, `system`; `shareable` — булево; `code` до 64 символов или `null`; `text` до 4000; `recorded_at` — время или `null`. Добавляет только домашняя клиника, для статусов `archived` и `deceased` запись закрыта.

Направление: `{"id", "patient_id", "from_clinic_id", "to_clinic_id", "reason", "status", "created_at", "created_by", "decided_at", "decided_by", "decision_note"}`. Статусы: `proposed` → `accepted` → `completed`, а также `rejected` и `cancelled`. Принять, отклонить и завершить может клиника-получатель, отменить — клиника-отправитель. Создать можно только от домашней клиники активного пациента в клинику — действующего партнёра, и только если у этого пациента между этой парой клиник нет направления в статусе `proposed` или `accepted` (иначе 409).

Неверная подпись на `route-candidates` и `referrals` не даёт отдельной ошибки: запрос уходит в ветку сотрудника и получает 403 `Authorization required` (или 404, если приложен токен сотрудника). На `by-ref` — 403 `Invalid interservice signature`.

Кандидаты маршрута: `{"patient_ref", "home_clinic_id", "candidates": [{"clinic_id", "clinic_name", "network", "role": "home" | "partner", "referral_required", "matched_capability": {...}}], "reason"}`. `reason`: `null`, `unknown_patient_ref`, `patient_<статус>` (в этих двух случаях ключа `home_clinic_id` в ответе нет), `no_clinic_with_capability`.

Карта:

- домашняя клиника: `{"visibility": "home", "patient": {...}, "anamnesis": [...все записи], "referrals": [...], "shared_with": [{"clinic_id", "clinic_name"}]}`. В `patient` — `id`, `patient_ref`, `home_clinic_id`, `home_clinic_name`, `full_name`, `birth_date`, `sex`, `contact`, `status`. Запись анамнеза в карте: `id`, `kind`, `code`, `text`, `recorded_at`, `author_role`, `clinic_id`, `version`, `shareable` — без `author_id`;
- партнёр с направлением в статусе `proposed`, `accepted` или `completed`: `{"visibility": "partner", "referral": {...}, "patient": {"id", "patient_ref", "home_clinic_id", "home_clinic_name", "status"}, "anamnesis": [...только shareable]}`. ФИО, дата рождения, пол и контакт добавляются в `patient` после `accepted`;
- остальным — 404 `Not visible to this clinic`.

Карта партнёра строится по последнему направлению в статусе `proposed`, `accepted` или `completed`. После `completed` партнёр видит ФИО и контакт бессрочно. Новое направление в статусе `proposed` снова скрывает их до принятия.

У направления одно решение: `decided_at`, `decided_by` и `decision_note` перезаписываются каждым действием. Комментарий к принятию пропадёт после `complete` без комментария.

Очередь: `{"kind": "incoming_referral", "referral_id", "patient_id", "patient_ref", "from_clinic_id", "reason", "created_at"}` — входящие в статусе `proposed`; `{"kind": "awaiting_completion", "referral_id", "patient_id", "patient_ref", "to_clinic_id", "created_at"}` — исходящие в статусе `accepted`.

Показатели: `clinic_id`, `patients_total`, `patients_by_status`, `referrals_outgoing`, `referrals_incoming`, `referrals_outgoing_accepted`, `anamnesis_entries`, `network_version`.

Чего нет:

- Списка возможностей клиник в API: они только в файле сети.
- Больше 500 пациентов в `GET /v1/patients`: список — только пациенты своей клиники, `limit` от 1 до 500.
- Истории решений по направлению: `decided_at`, `decided_by` и `decision_note` перезаписываются каждым действием.
- Сроков ожидания у партнёров и расписаний партнёров.

### Сеть клиник (`network.json`)

```json
{
  "version": "demo-network-1",
  "clinics": [{"id": "clinic-central", "name": "Central Clinic", "network": "demo-network", "active": true},
              {"id": "clinic-partner-1", "name": "Partner Clinic North", "network": "demo-network", "active": true}],
  "capabilities": [{"clinic_id": "clinic-central", "study_type": "ct", "anatomy": "CHEST",
                    "protocol_name": "CHEST_STANDARD", "finding_code": "*", "approved": true}],
  "partnerships": [{"clinic_a": "clinic-central", "clinic_b": "clinic-partner-1",
                    "direction": "mutual", "active": true, "since": "2026-01-01T00:00:00+00:00"}]
}
```

`finding_code: "*"` означает любую находку в этой области. `direction`: `outgoing` (из `clinic_a` в `clinic_b`), `incoming`, `mutual`. `study_type` — только `ct`, `mr`, `mammography`.

---

## Что между сервисами уже связано

- Сервис снимков → сервис пути: подписанное заключение после подтверждения врачом. Работает.
- Сервис пути → сервис клиники: в README клиники описано, в коде сервиса пути HTTP-клиента нет. `route-candidates` и `referrals` пока никто не вызывает.
