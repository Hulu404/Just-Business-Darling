# Just-Business-Darling

В этом репозитории находится локальный микросервис приёма DICOM, инференса через установленную локальную модель и врачебного подтверждения заключения. Сервис маршрутизации работает отдельно; заключение передаётся ему только после подтверждения врачом.

## Запуск из корня репозитория

```powershell
python -m pip install -r .\medmarshrut_image_service\requirements.txt
$env:REVIEWER_TOKEN = 'replace-with-long-random-secret'
python .\medmarshrut_image_service\service.py
```

API доступен на `http://127.0.0.1:8766`. По умолчанию корректное исследование направляется на ручной разбор, поскольку модель не подключена. Для локального ONNX backend задайте `MODEL_CONFIG` с путём к конфигурации модели; для явно тестового backend задайте `ENABLE_TEST_BACKEND=1`. Тестовый backend не анализирует изображения и не создаёт заключение.

Полный [контракт API, формата ZIP и манифеста](medmarshrut_image_service/README.md) находится в папке микросервиса.

## Тесты

```powershell
python -m unittest discover -s .\medmarshrut_image_service -p 'test_service.py' -v
```
