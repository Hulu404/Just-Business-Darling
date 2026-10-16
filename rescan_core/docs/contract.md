# Контракт события «анализы готовы» (зафиксирован 15.10.2026)

Единственный источник правды по полям, которые МИС отдаёт в `rescan_core`.
Фронтенд и отчёт зависят от него — менять только через ревью с командой.

## POST /v1/mis/results-ready

Заголовки:
- `X-Rescan-Signature` — HMAC-SHA256(тело, общий секрет), hex
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

## POST /v1/mis/visits-csv

Заголовки: те же (HMAC по байтам файла).
Тело: `multipart/form-data`, поле `file`.
CSV-колонки: `patient_token,visit_date,paid_amount,doctor_id`.

Ответ: `{"accepted": N, "errors": [{"line_number":..,"message":..,"raw":..}]}`.
Плохие строки не роняют загрузку — попадают в `errors`.
