# 01. Демо-стенд: три сервиса одной командой

## Зачем

Сейчас сервисы запускаются из трёх терминалов и с поставляемой конфигурацией ничего не маршрутизируют: модели нет, `rules.json` пуст, поэтому каждое исследование и каждое заключение уходит на ручной разбор. Прежде чем строить интерфейс, нужен стенд, на котором цепочка «снимок → подтверждение врача → эпизод → шаг → клиника-партнёр» проходит через настоящие сервисы на учебных данных.

## Сначала прочитай

- `CLAUDE.md` и `docs/api-contracts.md`.
- `medmarshrut_image_service/model.py` (`ModelBackend`, `TestBackend`), `service.py` (`StudyService.submit`, `_validate_result`, блок `__main__`), `test_service.py` (`synthetic_dicom`, `bundle`, `SyntheticModel`).
- `medmarshrut_path_service/rules.py`, `store.py` (`transition`, `revise_plan`, `confirmed_outcome`), `demo_two_cycles.py`.
- `medmarshrut_clinic_service/network.py`, `network.json`, `demo.py`.

## Что сделать

### 1. Папка `demo_stand/`

Всё, что нужно только для демонстрации, лежит здесь. Поставляемые `rules.json` и `network.json` не трогай: первый пуст намеренно, второй — пример автора сервиса. Стенд подставляет свои файлы через `PATH_RULES` и `CLINIC_NETWORK`.

**`synthetic_dicom.py`** — генератор учебных исследований. За основу возьми `synthetic_dicom` и `bundle` из тестов сервиса снимков. Изображения 256×256 с непостоянной яркостью (градиент или круги), чтобы было видно, что это рисунок, а не снимок. Тегов пациента нет. Три вида исследований:

| Исследование | `task` | `BodyPartExamined` | `ProtocolName` | `study_type` в сервисе пути |
|---|---|---|---|---|
| КТ органов грудной клетки, 3 среза | `ct_general` | `CHEST` | `CHEST_STANDARD` | `ct` |
| МРТ коленного сустава, 3 среза | `mr_general` | `KNEE` | `MR_KNEE` | `mr` |
| Маммография, 4 проекции | `mg_screening_2d` | `BREAST` | `MG_SCREENING` | `mammography` |

Генератор кладёт в папку состояния ZIP-архивы, манифесты к ним и `index.json`: `StudyInstanceUID` → список заданных признаков. У каждого пациента из таблицы наполнения своё исследование со своим UID; ещё несколько архивов остаются для загрузки из интерфейса.

**`image_demo_runner.py`** — сервис снимков со сценарным backend. Код самого сервиса не меняется: запускалка импортирует `StudyService` и `make_handler` и передаёт им свой backend. Обученной модели у команды нет, поэтому на стенде признаки заданы сценарием. Заготовка проверена на текущем коде для КТ, МРТ и маммографии:

```python
"""Image service with a scripted backend. Demo stand only: findings are scripted, pixels are never analysed."""
import json
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "medmarshrut_image_service"))
from model import ModelBackend  # noqa: E402
from service import StudyService, make_handler  # noqa: E402

MODEL_VERSION = "demo-scripted-1"


class DemoScriptedBackend(ModelBackend):
    def __init__(self, index_path: Path):
        self.index_path = index_path
        self.index: dict[str, list[dict]] = {}

    def load_model(self, model_path=None):
        self.index = json.loads(self.index_path.read_text(encoding="utf-8"))

    def check_compatibility(self, study, task):
        return study["modality"] == task.modality, "Modality does not match task"

    def infer_local(self, study, task, archive):
        base = {"kind": "model_inference", "backend": "DemoScriptedBackend", "model_version": MODEL_VERSION,
                "weights_sha256": "none", "preprocessing_version": "none", "modality": study["modality"],
                "anatomy": study["anatomy"], "protocol_name": study["protocol_name"],
                "diagnostic_task": "scripted demo, no image analysis",
                "input_quality": {"instance_count": study["instance_count"]},
                "limitations": ["Демо-сценарий: признак задан заранее, снимок не анализировался"]}
        script = self.index.get(study["study_uid"])
        if script is None:
            return {**base, "findings": [],
                    "refusal_reason": "Demo stand analyses only studies from the demo kit"}
        findings = []
        for item in script:
            for series_uid, series in study["series"].items():
                if study["modality"] == "MG":
                    sop_uid = next((k for k, v in series["projections"].items() if v == item["projection"]), None)
                    place = {"projection": item["projection"]}
                else:
                    order = series["ordered_sop_uids"]
                    sop_uid = order[item["slice_index"] - 1] if item["slice_index"] <= len(order) else None
                    place = {"slice_index": item["slice_index"]}
                if sop_uid:
                    findings.append({"code": item["code"], "description": item["description"], "confidence": 0.0,
                                     "localization": {"series_uid": series_uid, "sop_uid": sop_uid, **place}})
                    break
        return {**base, "findings": findings, "refusal_reason": None}


if __name__ == "__main__":
    service = StudyService(DemoScriptedBackend(Path(os.environ["DEMO_STUDY_INDEX"])),
                           router_url=os.environ.get("ROUTER_URL"), router_secret=os.environ.get("PATH_SHARED_SECRET"))
    server = ThreadingHTTPServer(("127.0.0.1", 8766), make_handler(service, os.environ["REVIEWER_TOKEN"]))
    print("DEMO image service (scripted findings, no image analysis): http://127.0.0.1:8766", flush=True)
    server.serve_forever()
```

Три свойства этого backend обязательны, не теряй их при доработке:

- исследование не из учебного набора получает отказ и уходит на ручной разбор. Чужой снимок не должен получить выдуманный признак;
- пустой список в `index.json` означает «находок нет»: сервис сам отправит такое исследование на ручной разбор;
- `model_version` начинается с `demo-`, `confidence` равен `0.0`, в `limitations` стоит честная пометка. По префиксу `demo-` интерфейс позже повесит плашку «демо-сценарий» и скроет оценку модели.

**`rules.demo.json`** — демо-правила для сервиса пути. Это пример работы маршрутизатора, а не клинические рекомендации: напиши об этом в `demo_stand/README.md`.

| `finding_code` | Область | Признак для врача (`description` в `index.json`) | `approved` | Шаги |
|---|---|---|---|---|
| `DEMO_CT_INFILTRATE` | `ct` / `CHEST` / `CHEST_STANDARD` | участок уплотнения лёгочной ткани | `true` | `appointment`: «Приём терапевта в течение 24 часов» |
| `DEMO_CT_NODULE` | `ct` / `CHEST` / `CHEST_STANDARD` | очаг в лёгком | `true` | `appointment`: «Консультация пульмонолога в течение 7 дней» |
| `DEMO_MR_MENISCUS` | `mr` / `KNEE` / `MR_KNEE` | участок изменённого сигнала в мениске | `true` | `appointment`: «Приём травматолога-ортопеда в течение 14 дней» |
| `DEMO_MG_DENSITY` | `mammography` / `BREAST` / `MG_SCREENING` | участок уплотнения ткани | `false` | `test`: «УЗИ молочных желёз»; `appointment`: «Приём маммолога» |

Последнее правило не утверждено намеренно: на нём показываем, что без утверждённого правила случай уходит врачу.

**`network.demo.json`** — демо-сеть клиник. Все возможности с `finding_code: "*"` и `approved: true`, оба партнёрства `mutual`.

| `clinic_id` | Название | Области |
|---|---|---|
| `clinic-central` | Клиника «Линия здоровья», Центральный филиал | все три |
| `clinic-partner-1` | Диагностический центр на Лесной | КТ грудной клетки, МРТ колена |
| `clinic-partner-2` | Маммологический центр «Опора» | маммография |

**`seed.py`** — наполняет стенд только через публичные API сервисов, без записи в базы напрямую. Исследования проходят настоящий путь: загрузка в сервис снимков, подтверждение врачом, эпизод в сервисе пути. Все пациенты зарегистрированы в сервисе клиники с домашней клиникой `clinic-central`, у каждого две-три записи анамнеза: часть с `shareable: true`, часть с `false`.

| `patient_ref` | Имя | Исследование и признак | Состояние после наполнения |
|---|---|---|---|
| `demo-patient-1` | Демо-пациент | КТ, `DEMO_CT_INFILTRATE` | эпизод активен, шаг открыт: пациент ещё не записался |
| `demo-patient-2` | Мария К. | маммография, `DEMO_MG_DENSITY` | ручной разбор, причина `rule_not_approved` |
| `demo-patient-3` | Олег Р. | КТ, `DEMO_CT_NODULE` | первый шаг пройден до итога врача; второй шаг `test` «Контрольная КТ органов грудной клетки» открыт, `due_at` шесть дней назад; направление в `clinic-partner-1` в статусе `proposed` |
| `demo-patient-4` | Елена П. | МРТ, `DEMO_MR_MENISCUS` | запись подтверждена на сегодня |
| `demo-patient-5` | Сергей Т. | КТ, `DEMO_CT_INFILTRATE` | визит состоялся, врач ещё не внёс итог |
| `demo-patient-6` | Игорь С. | КТ, `DEMO_CT_NODULE` | исследование ждёт проверки врача, эпизода нет |
| `demo-patient-7` | Нина В. | КТ без находок | ручной разбор в сервисе снимков, эпизода нет |

Сервис снимков узнаёт `patient_ref` только при подтверждении, поэтому `seed.py` сохраняет в папку состояния реестр `studies.json`: идентификатор задания → `patient_ref` и название исследования. Шлюз позже прочитает его.

Рядом положи два справочника.

`people.demo.json` — вымышленные люди стенда. Идентификаторы из него уходят в `actor`, `physician_id` и `author_id`, а шлюз в задании 02 возьмёт отсюда личности для ролей:

- сотрудники: координатор Наталья (`coordinator-natalia`), рентгенолог Д. Ершов, терапевт А. Соколова, пульмонолог В. Лебедев — ими подписаны события наполнения;
- кто стоит за ролью в интерфейсе: «сотрудник» — координатор Наталья; «врач» — один человек `doctor-demo` («Врач клиники, демо-роль»), он и подтверждает снимки, и вносит итоги приёма, как единственная роль врача в прототипе; «партнёр» — по одному сотруднику в `clinic-partner-1` и `clinic-partner-2`;
- пациенты: семь псевдонимов из таблицы выше с именами. Пациент по умолчанию — `demo-patient-1`.

`conclusions.demo.json` — тексты заключений, которыми `seed.py` подтверждает исследования: код находки → текст. Возьми черновики из прототипа (`DEMO[...].draft`) и поправь под КТ и МРТ колена. В тексте нет оценок модели и UID: это заключение врача, его увидит пациент.

**`smoke.py`** — сквозная проверка на своих данных (пациент с уникальным `patient_ref`, чтобы не зависеть от наполнения). Шаги, каждый с проверкой результата:

1. Регистрация пациента в сервисе клиники.
2. Загрузка учебной КТ: 201, `awaiting_physician`.
3. Загрузка КТ, которой нет в `index.json`: `manual_review`, признаков нет.
4. Подтверждение врачом с `patient_ref`: `routing_status` равен `sent`.
5. Эпизод в сервисе пути найден по `source_report_id`, статус `active`, шаг создан правилом.
6. `route-candidates` возвращает домашнюю клинику и партнёра с `referral_required: true`.
7. `offer` → `confirm` → `attend` → итог врача с одним следующим шагом: появляется шаг второго цикла.
8. Шаг второго цикла: `offer` → `refuse` → `revise-plan` → `offer` нового шага проходит (см. пункт 3 ниже).
9. Направление партнёру: до `accept` в карте партнёра нет ФИО, после — есть.
10. Учебная маммография того же пациента: после подтверждения эпизод в `manual_review` с причиной `rule_not_approved`.

### 2. `start.py` в корне

Сейчас это заглушка из одной строки. Сделай из неё запуск стенда:

- генерирует секреты и токены в памяти (`secrets.token_urlsafe`) и передаёт их процессам через окружение. На диск и в консоль секреты не пишутся; флаг `--print-secrets` печатает их для ручной работы с API;
- поднимает три процесса: `medmarshrut_path_service/service.py`, `medmarshrut_clinic_service/service.py` и `demo_stand/image_demo_runner.py`. `ROUTER_URL=http://127.0.0.1:8765/v1/reports`, один `PATH_SHARED_SECRET` у сервиса снимков и сервиса пути, свой токен сотрудника для каждой из трёх клиник в `CLINIC_STAFF_TOKENS`;
- папка состояния по умолчанию во временном каталоге системы, вне репозитория (`--state-dir` меняет путь). Каждый запуск начинается с чистой папки: задания сервиса снимков живут в памяти, и старые базы рядом с ними рассогласуются. Флаг `--keep` оставляет базы и поэтому отключает наполнение;
- перед стартом проверяет, что порты 8764–8766 свободны, и по-человечески объясняет, если нет;
- ждёт `/health` каждого сервиса. Если сервис не поднялся, показывает хвост его stderr;
- по умолчанию запускает `seed.py`; `--no-seed` пропускает;
- `--smoke` поднимает чистый стенд, наполняет его, выполняет `smoke.py`, останавливает всё и возвращает код завершения;
- `--image real` вместо сценарного backend запускает настоящий `medmarshrut_image_service/service.py` (с `MODEL_CONFIG`, если он задан). Наполнение в этом режиме честно покажет ручной разбор;
- по Ctrl+C останавливает дочерние процессы;
- список процессов описан данными: в задании 02 туда добавится шлюз.

Команда работает на Windows: только Python, `subprocess` с `sys.executable`, вывод в UTF-8.

### 3. Одна правка в сервисе пути

В `EpisodeStore.transition` (`medmarshrut_path_service/store.py`) проверка перед `offer` считает незавершённым любой предыдущий шаг, кроме `completed`. После отказа пациента и `revise-plan` старый шаг становится `superseded`, и новый шаг уже нельзя предложить: сервис отвечает 409 `Earlier plan step is unfinished`. Проверено на текущем коде. Считай `superseded` завершённым, как это уже делает `close_episode`. Добавь в `test_workflow.py` тест: `offer` → `refuse` → `revise-plan` → `offer` нового шага проходит.

Больше в сервисах ничего не меняй.

### 4. Мелочи

- `.gitignore` в корне: добавь `*.sqlite3` и `*.sqlite3-*` для всех папок.
- `demo_stand/README.md`: что такое стенд, как запускать, какие данные учебные, почему backend сценарный.
- В корневой `README.md` добавь раздел «Запуск стенда одной командой». Остальной текст не переписывай: это задача задания 08.

## Готово, когда

- `python start.py --smoke` завершается с кодом 0 и печатает прохождение каждого шага.
- `python start.py` поднимает три сервиса и наполняет их; в `GET /v1/staff/queue` сервиса пути видны случаи из таблицы наполнения.
- Тесты трёх сервисов зелёные, в сервисе пути на один тест больше.
- В сервисе снимков и сервисе клиники нет ни одной изменённой строки; в сервисе пути изменено одно условие и добавлен тест.
- В репозитории нет секретов, баз и архивов DICOM.

## Отчёт

`docs/reports/01-stand.md` по правилам из `CLAUDE.md`: что создано, как запустить, вывод `--smoke`, правка в сервисе пути. Создай ветку `feature/web-product` от `develop`, если её ещё нет. В этот же коммит добавь `CLAUDE.md`, `docs/`, `prompts/` и `prototype/`, если они ещё не в git.
