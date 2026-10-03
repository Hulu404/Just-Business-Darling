# Just-Business-Darling

В этом репозитории находится отдельный локальный микросервис приёма и проверки медицинских исследований DICOM. Существующий сервис маршрутизации работает отдельно и не изменён.

## Запуск из корня репозитория

```powershell
python -m pip install -r .\medmarshrut_image_service\requirements.txt
python .\medmarshrut_image_service\service.py
```

API доступен на `http://127.0.0.1:8766`. По умолчанию корректное исследование направляется на ручной разбор, поскольку модель не подключена. Для явно тестового backend задайте `$env:ENABLE_TEST_BACKEND = '1'` перед запуском; он не анализирует изображения.

Полный [контракт API, формата ZIP и манифеста](medmarshrut_image_service/README.md) находится в папке микросервиса.

## Тесты

```powershell
python -m unittest discover -s .\medmarshrut_image_service -p 'test_service.py' -v
```
