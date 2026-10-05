# Сервис карты пациента клиники

`medmarshrut_clinic_service` — это сервис клиники: жизненный цикл пациента внутри клиники, карта с анамнезом, видимость пациента клиниками-партнёрами при маршрутизации. Он не анализирует снимки и не формирует маршрут — он отвечает на вопросы «кто этот пациент по `patient_ref`», «что в его карте», «какие клиники-партнёры могут принять его по этому профилю».

Сервис слушает `127.0.0.1:8764`, хранит данные в SQLite, использует только стандартную библиотеку Python. Межсервисный обмен — HMAC-SHA256 (как в `medmarshrut_path_service`).

## Роль в архитектуре

- `medmarshrut_image_service` → выдаёт `patient_ref` (псевдоним) в подтверждённом заключении, но не знает личность.
- `medmarshrut_path_service` → хранит `Episode` по `patient_ref`, `study_type`, `anatomy`, `protocol_name`, `finding_code`. Умеет запросить у клиники, куда маршрутизировать.
- `medmarshrut_clinic_service` → владеет соответствием `patient_ref ↔ пациент`, картой, анамнезом, сетью клиник, партнёрствами и ответом на запрос маршрутизации.

## Запуск

```powershell
$env:CLINIC_SHARED_SECRET = 'replace-with-random-shared-secret'
$env:CLINIC_ADMIN_TOKEN = 'replace-with-random-admin-token'
$env:CLINIC_STAFF_TOKENS = '{"replace-with-clinic-a-token":"clinic-central","replace-with-partner-token":"clinic-partner-1"}'
$env:CLINIC_DB = 'D:\local-state\clinic.sqlite3'
$env:CLINIC_NETWORK = 'D:\projects\medmarshrut_clinic_service\network.json'
python .\medmarshrut_clinic_service\service.py