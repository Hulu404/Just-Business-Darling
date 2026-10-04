# 12. Кабинет врача rescan на данных шлюза

Задание выполняется циклами по `prompts/rescan-loop.md`. Память цикла — «Ход работ» ниже.

## Ход работ

- [x] **Цикл 0. Разведка и опора** — 2026-10-04 22:20
  - Создан отчёт с «Ходом работ». Образец на месте (`prototype/rescan-app-standalone.html`, untracked).
  - Установлены недостающие зависимости окружения: `pydicom`, `numpy`, `Pillow`, `onnxruntime`, `anthropic`, `playwright` + chromium (без них исходные наборы падали на импорте, код ни при чём).
  - Полная проверка до правок кода: быстрая — image 20, path 12, clinic 8, medications 10, gateway 87 OK (skipped=6, тесты PostgreSQL без `GATEWAY_TEST_DATABASE_URL`); smoke 22/22; web-check 7/7 (сравнение с прототипом 8 экранов, макс. расхождение 0.060%).
  - Написан `prototype/rescan_extract.py`: шрифт → `web/fonts/Stolzl-Regular.otf` (OTTO, 57948 Б), `IMG` (20 форм) и `ORG` (5 органов: lungs, heart, adrenal, brain, knee) → `web/img/rescan/*.webp` (RIFF), текст без base64 → `prototype/rescan-app-text.html` (149 КБ). Портреты `AVS` не извлекаются. Скрипт идемпотентен: повторный запуск — те же хеши.
  - `.gitignore`: добавлены `prototype/rescan-app-standalone.html`, `prototype/rescan-app-text.html`, `medmarshrut_gateway_service/web/fonts/`.
  - Правка `test_gateway.py`: текстовые проверки (`localStorage`/URL/`on…=`) теперь только для `.html/.css/.js/.svg` (новая константа `TEXT_SUFFIXES`); поиск секретов — по байтам всех файлов. После правки gateway 87 OK (skipped=6) с .webp и .otf в `web/`.
  - Проверено: исходные проверки зелёные (числа выше); после скрипта и правки тестов быстрая зелёная; повторный запуск скрипта файлы не меняет. Отступлений от задания нет.
  - В коммит: `prompts/{12,13,14,15}-*.md`, `prompts/rescan-loop.md`, `prompts/rescan-README.md`, `prototype/rescan_extract.py`, `.gitignore`, `web/img/rescan/*.webp`, `test_gateway.py`, отчёт. Чужое (`prompts/09`, `PROGRESS_*`, `debug.log`, презентация) не трогалось.
- [x] **Цикл 1. Шлюз: статика и защита** — 2026-10-04 22:30
  - `STATIC_TYPES`: добавлены `.webp` → `image/webp` и `.otf` → `font/otf`. В `CSP` добавлен `font-src 'self'`.
  - Константа `BRAND_FONT = web/fonts/Stolzl-Regular.otf`; `GET /api/health` отдаёт `brand_font` (`.is_file()`).
  - Тесты (`StaticTests`): `.otf`/`.webp` отдаются с верным типом на временной папке (патч `service.WEB_DIR`, шрифта в git нет); `/assets/index.txt` 404; CSP содержит `font-src 'self'` и `script-src 'self'`; `brand_font` false без файла, true с файлом (патч `service.BRAND_FONT`). Строка в README шлюза.
  - Проверка (быстрая): image 20, path 12, clinic 8, medications 10, gateway 90 OK (было 87, +3 теста; skipped=6 — PostgreSQL). Отступлений нет.
- [x] **Цикл 2. Шлюз: предпросмотр шага** — 2026-10-04 22:40
  - `GET /api/doctor/studies/{id}` для `awaiting_physician` отдаёт `item["preview"]`: по каждому коду находки `POST /v1/rules/dry-run` сервиса пути (`study_type` из `MODALITY_TYPES`, `anatomy`, `protocol_name`, `finding_code`) → `steps`, `manual_reason`, `rule_version`, плюс `explanation` из `store.explanation` или `null`. `confidence` в запрос не входит. Сервис пути недоступен (`GatewayError`) или scope неполный — `preview: null`.
  - Helper `_study_preview(job)` в `service.py`. Строка в README шлюза.
  - Тесты (`test_imaging.StudyRouteTests`, +4): шаг по утверждённому правилу (и проверка тела запроса без `confidence`); причина при неутверждённом; `preview: null` при `path.mode="drop"`; 403 пациенту и координатору.
  - Проверка (быстрая): image 20, path 12, clinic 8, medications 10, gateway 94 OK (было 90, +4; skipped=6). Отступлений нет.
- [ ] Цикл 3. Шлюз: место и специалист записи
- [ ] Цикл 4. Каркас кабинета
- [ ] Цикл 5. «Исследования»
- [ ] Цикл 6. «Приёмы»
- [ ] Цикл 7. «Пациенты»
- [ ] Цикл 8. «Сегодня», колокольчик, «Настройки»
- [ ] Цикл 9. Переключение
- [ ] Цикл 10. Ревизия
- [ ] Финал

## Примечания окружения

- Зависимости ставятся в `.venv` из `requirements.txt` сервисов. Браузер для web-check: `python -m playwright install chromium`.
- Тесты PostgreSQL (6 шт. в gateway) идут только с `GATEWAY_TEST_DATABASE_URL`; без неё пропускаются.
