# P4 — контракты между компонентами

Это **предлагаемые интерфейсы для согласования в PR**. Они фиксируют входы, выходы и поведение. Реализации API, SQLite и JobRunner делаются в отдельных PR.

## 1. Кто кого вызывает

`FastAPI → JobServicePort (реализация Василия) → JobRepositoryPort (реализация Кости) → SQLite`.

`JobRunner → Dispatcher → Registry → Tools` — уже реализованное ядро P3. Python Protocol не создаёт отдельного сервера.

## 2. API - JobService

`services/contracts.py` — основной источник сигнатур; не дублировать DTO в `api/`.

- `create_job(CreateJobCommand) -> CreateJobOutcome` — `replayed=False` → HTTP 202, `True` → HTTP 200 и `Idempotency-Replayed: true`.
- `get_job(client_id=..., job_id=...) -> JobSnapshot` — чужой и несуществующий Job одинаково приводят к `JOB_NOT_FOUND` / HTTP 404.
- `list_jobs(client_id=..., status=..., operation=..., limit=..., offset=...) -> JobPage` — только Job клиента.
- `GET /api/v1/jobs/{job_id}/result` использует `get_job`, затем возвращает 200 для `done`, 202 для `created`/`running`, 409 для `failed`.
- `X-API-Key` проверяется на уровне API и превращается в `client_id`. **Не** принимать `client_id` из JSON/form запроса.
- Тело POST: `multipart/form-data` с `file` + `operation`; максимум 10 MiB; `Idempotency-Key` необязательный по P2 OpenAPI.
- Единая форма ошибки: `{"error":{"code":"...","message":"...","details":[{"field":"...","issue":"..."}]}}`.
- `JobSnapshot.error/result` — JSON-совместимые словари, не `ToolError`-объекты или SQL-строки. `JobStatus` сериализуется строкой.

## 3. JobService - Repository

`repositories/contracts.py` — основной источник сигнатур.

- `create_or_get` выполняет **одну атомарную операцию** создания и регистрации идемпотентности. `request_hash` вычисляется по **операции и точным байтам документа** (например SHA-256 от однозначного кодирования этих двух частей). При повторе того же ключа и тела — `replayed=True` и прежний Job, даже если тот уже `failed`. При другом содержимом — `IdempotencyConflictError` → сервис преобразует её в `ServiceError(code="IDEMPOTENCY_KEY_CONFLICT")` → API 409.
- `get` и `list_jobs` фильтруют по `client_id`; чужой ID не раскрываем.
- `save_transition(job, expected_status)` сохраняет статус **вместе** с `result/error` и историей (если хранится) в одной SQLite-транзакции с проверкой исходного статуса. Конкурентный повтор не должен перезаписывать результат.
- `list_unfinished()` — `created` возвращаем в очередь, `running` переводим в `failed` с `WORKER_INTERRUPTED`; терминальные состояния не трогаем.

### Важная интеграция с Dispatcher P3

Сейчас `Dispatcher.dispatch(job)` делает `job.start()`, вызывает Tool и завершает Job **внутри одного метода**. Для P4 необходимо зафиксировать `running` в БД **до вызова Tool**, иначе при перезапуске нельзя надёжно отличить выполнявшийся Job от ещё не запущенного.

Минимальный совместимый вариант — расширить метод `Dispatcher.dispatch(job, on_started=None)`, где callback вызывается **после** `job.start()`, но **до** `tool.execute()`. JobRunner передаёт callback, который выполняет `repository.save_transition(job=job, expected_status=JobStatus.CREATED)`. После завершения Tool Runner сохраняет `done/failed` через `save_transition(..., expected_status=JobStatus.RUNNING)`.

`on_started` — изменение для согласования с автором Dispatcher, **пока не реализовано**. Не пытайтесь дважды вызвать `job.start()` (сначала Runner, потом Dispatcher): Job это отвергнет. Если запись running в БД не удалась, Tool запускать нельзя.

### Восстановление Job из SQLite

В P3 конструктор `Job(...)` создаёт новый UUID и состояние `created`. При чтении записи из БД нужно восстановить **тот же UUID, состояние, результат, ошибку и даты**, не создавая новую логическую Job. Косте и Василию нужно согласовать безопасный `Job.restore(...)` или отдельную фабрику для восстановления. **Напрямую менять `_status` из SQL-репозитория не рекомендуется**. Это отдельная небольшая интеграционная доработка P3.

### Файлы на диске + SQLite

БД хранит `document_ref`, сам PDF/TXT — в постоянной директории (вне `tmp`). Файл и транзакция SQLite не образуют одну общую транзакцию: при повторе/ошибке создания убирайте временный лишний файл; запускать Job можно только после коммита. При восстановлении хранилища повторная обработка `created` возможна только если файл сохранился.

## 4. Требования к таблицам

Костя выбирает схему и миграции, но должны храниться как минимум `jobs` (id, client_id, operation, filename, media_type, document_ref, options, status, result, error, created_at, updated_at) и связка `idempotency_keys` (client_id, key, request_hash, job_id), UNIQUE по `(client_id, key)`; миграции применять отдельно, не `CREATE TABLE` при запуске приложения.

## 5. Что проверить перед Merge

- `python -m pytest` на объединённых PR.
- Повтор POST с тем же ключом не создаёт вторую Job; с другим содержимым возвращает 409; идентификаторы разных клиентов изолированы.
- Создание, чтение результата и миграции проверяются API-тестами.
- После перезапуска сохраняются Job и их результаты.
- `running` фиксируется до выполнения Tool; после сбоя восстанавливается как `failed`.
- OpenAPI из `docs/api/openapi.yaml` соответствует реальным маршрутам, формату ошибок и статусам.
- Тесты Н40–Н49 из P4: применимые случаи покрыты, неприменимые обоснованы в отчёте.
