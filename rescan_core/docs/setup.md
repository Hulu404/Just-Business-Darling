# Настройка и проверка rescan_core (для всех в команде)

Пошагово: что установить, как поднять проект, как проверить код и базу.
Инструкция рассчитана на Windows, но команды для macOS/Linux отмечены.

---

## 1. Что установить на компьютер

| Что | Зачем | Откуда | Проверка |
|---|---|---|---|
| **Python 3.13** | язык бэкенда | python.org → скачать 3.13.x. На Windows **поставь галочку «Add Python to PATH»** | `python --version` → `Python 3.13.x` |
| **PostgreSQL 16** | основная база (в проде — хосте в РФ) | postgresql.org/download. При установке **запомни пароль пользователя `postgres`** | `psql --version` |
| **Git** | версии и клонирование | git-scm.com | `git --version` |
| **VS Code** | редактор и отладка | code.visualstudio.com | — |
| **DBeaver** | смотреть базу глазами (у тебя уже есть ✅) | — | подключение к `localhost:5432` |
| **Insomnia или Postman** *(по желанию)* | дёргать API вручную | insomnia.rest | — |

Расширения VS Code (поставятся сами из `.vscode/extensions.json`, либо вручную):
**Python**, **Pylance**, **Ruff**, **Mypy Type Checker**.

> На Windows при установке PostgreSQL инсталлятор создаёт службу и запускает её.
> Если база «не отвечает» — открой «Службы» (services.msc) и проверь, что служба
> `postgresql-x64-16` запущена.

---

## 2. Создать базу и пользователя

Открой **SQL Shell (psql)** из меню «Пуск» (пароль — тот, что задала при
установке) и выполни по очереди:

```sql
CREATE USER rescan WITH PASSWORD 'rescan';
CREATE DATABASE rescan_core OWNER rescan;
```

Это ровно те логин/пароль/имя, что стоят в `.env.example`. Менять можно, но
тогда не забудь поправить `DATABASE_URL`.

---

## 3. Поднять проект

```bash
git clone <адрес-репозитория> rescan_core
cd rescan_core

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
cp .env.example .env          # Windows: copy .env.example .env
```

Открой `.env` и проверь строку подключения:

```
database_url=postgresql+psycopg://rescan:rescan@127.0.0.1:5432/rescan_core
```

Формат: `postgresql+psycopg://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@ХОСТ:ПОРТ/ИМЯ_БАЗЫ`.

---

## 4. Создать таблицы и демо-данные

```bash
python -m scripts.seed_demo
```

Что произошло: накатилась миграция (создались 16 таблиц) и записалась одна
демо-клиника с врачами, форматами и целями. Команду можно запускать повторно —
она ничего не дублирует.

Проверить таблицы вручную (в psql или DBeaver):

```sql
\dt                       -- список таблиц (в psql)
SELECT * FROM clinics;    -- должна быть одна строка
SELECT name FROM sqlite_master;  -- только если работаешь на SQLite
```

Ожидаешь увидеть 16 таблиц: `clinics, branches, doctors, formats, goals,
patients, contacts, episodes, steps, messages, requests, visits, consents,
events, audit_events, outbox` (плюс служебная `alembic_version`).

---

## 5. Запустить сервер

```bash
uvicorn app.main:app --reload
```

Открой `http://127.0.0.1:8000/docs` — это Swagger со всеми эндпоинтами.
Живость проверяется тут: `http://127.0.0.1:8000/health` — должен вернуть
`{"status":"ok","database":"ok",...}`.

---

## 6. Проверить работу (сквозной сценарий)

Событие требует HMAC-подписи, поэтому удобнее мини-скриптом. Сохрани как
`send_event.py` в корне проекта и запусти `python send_event.py`:

```python
import hashlib, hmac, json, time, urllib.request

body = json.dumps({
    "event_id": "evt-manual-1",          # поменяй, чтобы получить новый эпизод
    "branch_id": "br-1",
    "patient_token": "pt-manual-1",
    "phone": "+79001234567",
    "ordering_doctor_id": "doc-1",
    "ready_at": "2026-10-14T09:00:00+03:00",
    "marketing_consent": True,
}).encode()

sig = hmac.new(b"dev-only-change-me", body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://127.0.0.1:8000/v1/mis/results-ready", data=body,
    headers={"X-Rescan-Signature": sig,
             "X-Rescan-Timestamp": str(int(time.time())),
             "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
```

**Что должно получиться:**
- Первый запуск → `{"status":"created","episode_id":"...","group":"main|control"}`.
- Второй запуск тем же `event_id` → `{"status":"duplicate",...}` — второй эпизод
  НЕ создаётся. Это и есть проверка идемпотентности (требование B2).
- В DBeaver/SQL проверь: в `episodes` одна строка, в `events` одна строка,
  в `patients.group` заполнена, в `contacts.phone_enc` — нечитаемый шифротекст,
  в `audit_events` — запись `mis.event.accepted`.

---

## 7. Тесты, линтер, типы

```bash
pytest                                              # все тесты
pytest tests/test_ingest.py -v                      # один файл подробно
pytest -k duplicate                                 # тесты по слову в названии
ruff check .                                        # стиль и ошибки
mypy app                                            # типы
```

Ожидается: **20 тестов passed**, `ruff` — «All checks passed», `mypy` —
«Success: no issues found».

---

## 8. Работа с миграциями (когда меняешь модели)

```bash
# после правки app/db/models.py:
alembic revision --autogenerate -m "краткое описание изменения"
alembic upgrade head        # применить
alembic downgrade -1        # откатить одну назад
alembic current             # какая версия сейчас применена
```

Правило: **модель и миграция должны совпадать**. Если меняешь таблицу — сначала
модель, потом autogenerate, потом upgrade. Не правь таблицы руками в DBeaver —
при следующей миграции изменения потеряются.

---

## 9. Тестирование прямо в VS Code

1. Открой папку `rescan_core` (File → Open Folder).
2. `Ctrl+Shift+P` → **Python: Select Interpreter** → выбери `.venv`.
3. Панель **Testing** (иконка колбы слева): VS Code подхватит pytest. ▶ сверху —
   все тесты; ▶ рядом с тестом — один; жук — отладка с точками останова.
4. Отладка сервера: `Ctrl+Shift+D` → `rescan_core: uvicorn` → F5. Точки останова
   в коде работают.
5. Отладка заливки демо-данных: конфигурация `seed_demo: залить демо-данные`.

---

## 10. Частые проблемы

| Симптом | Причина и что делать |
|---|---|
| `connection refused` к 5432 | PostgreSQL не запущен → «Службы» → запусти `postgresql-x64-16` |
| `password authentication failed` | пароль в `DATABASE_URL` не совпадает с тем, что задала при установке |
| `relation "clinics" does not exist` | не накатаны миграции → `alembic upgrade head` |
| «в базе нет ни одной клиники» | не запущен `python -m scripts.seed_demo` |
| `401 bad signature` | подпись считается не по тому телу; секрет в `.env` и в скрипте должны совпадать |
| `401 stale signature` | `X-Rescan-Timestamp` старше 300 секунд — пересчитай |
| `ModuleNotFoundError: app` | не активировано виртуальное окружение или не сделан `pip install -e .` |
| тесты «не видят» `.venv` | выбери интерпретатор заново (шаг 2 раздела 9) |

---

## 11. Правила безопасности (не нарушать)

- Файл `.env` в git **не коммитится** — там секреты. В репозитории только
  `.env.example`.
- Телефон пациента хранится только в таблице `contacts` и только зашифрованным.
  В логи и аудит телефоны не попадают.
- Результатов анализов, диагнозов и PDF в системе нет и быть не должно.
- В проде база — на хосте в РФ (требование к персональным данным).
