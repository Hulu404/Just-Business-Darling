# Воспроизводимый контур обучения

Этот контур обучает **отдельный бинарный классификатор одного признака на одном DICOM изображении** для конкретной комбинации модальности (`CT`, `MR` или `MG`), анатомической области и `ProtocolName`. Он соответствует контракту `LocalONNXBackend`: вход `[1,1,H,W]`, выход — одна вероятность. Исследование и пациент используются для разделения выборок, а не как вход модели. Это исследовательский шаблон, не валидированная медицинская модель. Для задач на уровне исследования, сегментации, 3D объёма или BI-RADS нужны отдельные модель, разметка, метрики и проверка.

## Данные и права

Обучение не начинается без флага `--allow-real-data`. Перед его применением ответственное лицо должно подтвердить право использовать набор для этой цели, согласованную деидентификацию DICOM, контроль доступа и хранение данных внутри разрешённого контура. Код проверяет схему и соответствие части DICOM метаданных манифесту, но **не гарантирует обезличивание**: отдельно проверяйте теги, private tags, burned-in annotations, вложенные документы и связь псевдонимов. Исходные файлы и идентификаторы пациента не входят в артефакт модели.

Манифест — UTF-8 JSONL, одна строка на изображение; пути к `.dcm` относительны папке манифеста и не могут выходить за неё. Обязательные поля:

```json
{"study_id":"1.2.3.4","patient_id":"pseudonym-001","institution_id":"site-01","modality":"CT","anatomy":"CHEST","protocol_name":"CHEST_STANDARD","study_type":"routine_noncontrast","image_path":"images/001.dcm","image_sha256":"64 lowercase hex digits of DICOM file SHA-256","label":1,"label_source":{"kind":"expert","reference":"adjudication-42"},"finding_location":{"series_uid":"1.2.3.5","sop_uid":"1.2.3.6","region":"slice:1"},"annotation_version":"v1"}
```

`study_id` должен совпадать с обезличенным DICOM `StudyInstanceUID`; `series_uid` и `sop_uid` — с идентификаторами изображения. `image_sha256` фиксирует точные байты файла и проверяется при каждом чтении манифеста. `patient_id` — устойчивый псевдоним **между всеми учреждениями**, чтобы пациент не попал в разные части; пациент, встретившийся в двух учреждениях, требует ручного разрешения и отвергается. `study_type` задаёт клинически значимый тип исследования для отчёта ошибок. `label` — 0/1 для конкретного изображения и одного целевого признака. `label_source.kind`: `expert`, `pathology`, `follow_up`, `registry`; `reference` — псевдоним записи происхождения метки. `finding_location.region` — непустая локализация, согласованная с протоколом разметки; для отрицательных примеров строго `none`. `annotation_version` фиксирует версию правил и экспертов. Нужны независимая экспертиза, разрешение расхождений, определение отрицательных случаев и аудит качества меток. Формат локализации здесь не является геометрической разметкой: координатные метрики без дополнительной схемы не вычисляются.

## Конфигурация и запуск

Установите базовые зависимости из `requirements.txt`; для обучения дополнительно `requirements-train.txt`. Файл задачи, например `task.json`:

```json
{
  "model_version":"ct-chest-finding-v1", "task":"ct_general", "modality":"CT",
  "anatomy":"CHEST", "protocol_name":"CHEST_STANDARD",
  "diagnostic_task":"single chest finding on one image", "label_code":"FINDING_X",
  "label_description":"clinician approved finding wording", "input_size":[512,512],
  "threshold":0.8, "epochs":20, "batch_size":8, "learning_rate":0.0001,
  "seed":42, "preprocessing_version":"monochrome-v1",
  "limitations":["Example architecture; clinical validity has not been established"]
}
```

Для МРТ используйте `mr_general`/`MR`, для маммографии `mg_screening_2d`/`MG`; создайте отдельную конфигурацию и версию для каждого признака и протокола. Порог выбирают по валидации в рамках клинической постановки до просмотра test/external. Нужные команды из корня проекта:

```powershell
python .\medmarshrut_image_service\training.py validate --manifest D:\data\manifest.jsonl --config D:\data\task.json
python .\medmarshrut_image_service\training.py split --manifest D:\data\manifest.jsonl --config D:\data\task.json --external-institution site-02 --seed 42 --output D:\data\split.json
python .\medmarshrut_image_service\training.py train --manifest D:\data\manifest.jsonl --config D:\data\task.json --split D:\data\split.json --artifact D:\models\ct-chest-finding-v1 --allow-real-data
python .\medmarshrut_image_service\training.py evaluate --manifest D:\data\manifest.jsonl --artifact D:\models\ct-chest-finding-v1 --partition external
```

`split.json` связывается SHA-256 с точными байтами манифеста. Пациенты не пересекаются между train/validation/test/external; external содержит только другое учреждение. При изменении манифеста требуется новый split и новый артефакт. Артефакт создаётся в новой папке с именем `model_version`: `model.onnx`, `checkpoint.pt`, `model.json`, `train_config.json`, `split.json`, `metrics.json`, `model_card.json`. ONNX и `LocalONNXBackend` используют одну функцию `dicom_tensor` и версию `monochrome-v1`. Пиксели каждого изображения отдельно нормируются по min/max, MONOCHROME1 инвертируется, масштабирование билинейное. На смешанные серии, объёмные или иные задачи этот контракт автоматически не переносится.

Отчёт содержит image-level sensitivity/recall, specificity, precision, TP/TN/FP/FN, Brier score, 10-bin ECE и таблицу калибровки, разрезы по учреждению, типу исследования и версии разметки, ошибки FP/FN по типам. Неопределимые дроби возвращаются как `null`. Интервалы неопределённости, метрики на пациента/исследование, локализация (например, lesion sensitivity/FROC/IoU), выбор порога, проверка смещения, дрейфа и межэкспертного согласия требуют отдельного плана для конкретной задачи и достаточной выборки. Малый внешний набор не доказывает переносимость.

## Ручной допуск

Изучите карточку, метрики внешнего набора, ошибки, документацию разметки и клиническую валидацию. Только уполномоченный специалист после решения создаёт запись допуска:

```powershell
python .\medmarshrut_image_service\training.py approve --artifact D:\models\ct-chest-finding-v1 --approved-by reviewer-id --decision-record review-ticket-123
```

`approval.json` связывает решение с SHA-256 конфигурации, весов, отчёта, карточки и файлов воспроизводимости. Без записи или после изменения любого из них `LocalONNXBackend` не загрузит версию. Ручной допуск в этой программе — технический барьер, не замена разрешения регулятора или клинического исследования. Установите `MODEL_CONFIG=D:\models\ct-chest-finding-v1\model.json` для сервиса.

## Ресурсы и клиническая проверка

PyTorch и экспорт ONNX требуют достаточной RAM/VRAM под размер изображения и batch; ориентир для этого малого 2D CNN — GPU с CUDA и не менее 8 ГБ VRAM при 512×512 и batch 8, но точные требования измеряются на целевом оборудовании. CPU допустим для технической проверки и малых синтетических наборов, длительное обучение на нём может быть непрактично. Зафиксируйте версии Python, PyTorch, CUDA/драйвера и аппаратуры рядом с каждым реальным экспериментом. В production нужны независимые тесты на других учреждениях, заранее заданные критерии безопасности и клинической полезности, анализ подгрупп и ошибок, калибровка, наблюдение за дрейфом и врачебный контроль результата.

Синтетические тесты: `python -m unittest discover -s medmarshrut_image_service -p 'test_*.py' -v`.
