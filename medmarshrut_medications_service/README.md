# Сервис медикаментов

`medmarshrut_medications_service` — это маркетплейс лекарств внутри приложения: принимает **подтверждённый врачом рецепт** от path-сервиса или МИС, находит его в каталоге партнёрских аптек и даёт пациенту оформить заказ. Сервис слушает `127.0.0.1:8767`.

## Ключевой принцип

Сервис **не подбирает лечение**. Он **исполняет** назначение врача:

- матчинг — только по точной тройке `(INN, form, strength)`;
- если `substitution_allowed: false`, показывается только конкретное `trade_name`;
- если `substitution_allowed: true`, разрешены аналоги с тем же INN/form/strength;
- заказать можно не больше, чем выписал врач;
- после `expires_at` рецепт недействителен.

## Оплата и доставка

**Сервис не проводит оплату и не хранит платёжные данные.** Оплата, доставка, чек и возврат — на стороне аптеки-партнёра. Наш сервис:

1. Принимает подтверждённый рецепт.
2. Сопоставляет его с каталогом и остатками партнёрских аптек.
3. Создаёт заказ со статусом `placed`.
4. Возвращает пациенту `redirect_url` — прямую ссылку на оформление в аптеке-партнёре.

Пациент открывает ссылку, платит и оформляет доставку **в интерфейсе аптеки**. Аптека сама подтверждает оплату, готовит заказ, передаёт курьеру.

Когда аптека обновляет статус (`confirm` → `ready` → `picked_up`), `redirect_url` пропадает — заказ уже исполнен.

## Запуск

```powershell
$env:MED_SHARED_SECRET = 'replace-with-random-shared-secret'
$env:MED_ADMIN_TOKEN = 'replace-with-random-admin-token'
$env:MED_PATIENT_TOKEN = 'replace-with-random-patient-token'
$env:MED_STAFF_TOKENS = '{"replace-with-staff-token":"pharmacy-1"}'
$env:MED_DB = 'D:\local-state\medications.sqlite3'
$env:MED_CATALOG = 'D:\projects_X\Just-Business-Darling\medmarshrut_medications_service\catalog.json'
$env:MED_INVENTORY = 'D:\projects_X\Just-Business-Darling\medmarshrut_medications_service\pharmacies.json'
python .\medmarshrut_medications_service\service.py