# Just-Business-Darling

В репозитории находятся локальный сервис снимков и отдельный [сервис сопровождения пациента](medmarshrut_path_service/README.md). Заключение передаётся после подтверждения врачом, включая МРТ.

## Запуск из корня репозитория

```powershell
python -m pip install -r .\medmarshrut_image_service\requirements.txt
$env:REVIEWER_TOKEN = 'replace-with-long-random-secret'
$env:ROUTER_URL = 'http://127.0.0.1:8765/v1/reports'
$env:PATH_SHARED_SECRET = 'replace-with-at-least-16-random-characters'
python .\medmarshrut_image_service\service.py
```

API доступен на `http://127.0.0.1:8766`. По умолчанию корректное исследование направляется на ручной разбор, поскольку модель не подключена. Для локального ONNX backend задайте `MODEL_CONFIG` с путём к конфигурации модели; для явно тестового backend задайте `ENABLE_TEST_BACKEND=1`. Тестовый backend не анализирует изображения и не создаёт заключение.

Полный [контракт API, формата ZIP и манифеста](medmarshrut_image_service/README.md) находится в папке микросервиса.

Сервис маршрута запускается в другом терминале с тем же `PATH_SHARED_SECRET` и отдельным `PATH_ADMIN_TOKEN`. Полные команды и контракт приведены в его README. Поставляемые правила пусты: заключения требуют ручного разбора до утверждения правил клиникой.

## Запуск стенда одной командой

```powershell
python -m pip install -r .\medmarshrut_image_service\requirements.txt
python start.py
```

Команда поднимает сервисы пути (8765), клиники (8764) и снимков (8766) с учебными данными и сценарным backend снимков, наполняет их семью демо-пациентами и работает до Ctrl+C. Секреты создаются в памяти на каждый запуск, `--print-secrets` печатает их для ручной работы с API. Сквозная проверка: `python start.py --smoke`. Остальные флаги и что на стенде имитируется — в [demo_stand/README.md](demo_stand/README.md).

## Тесты

```powershell
python -B -m unittest discover -s .\medmarshrut_image_service -p 'test_*.py' -v
python -B -m unittest discover -s .\medmarshrut_path_service -p 'test_*.py' -v
```
