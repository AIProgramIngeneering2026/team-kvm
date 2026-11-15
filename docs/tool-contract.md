# Tool Contract

## 1. Назначение

Документ описывает общий внутренний контракт инструментов обработки документов, которые вызываются компонентом `Dispatcher` через `Registry`.

В MVP предусмотрены два инструмента:

- `ExtractTextTool` — извлечение текста;
- `TextStatisticsTool` — подсчёт статистики текста.

Оба инструмента используют общий `DocumentReader` для чтения PDF и TXT. Инструменты не должны самостоятельно реализовывать разбор PDF или декодирование TXT.

## 2. Общая схема взаимодействия

1. `JobRunner` передаёт `Dispatcher` данные сохранённой Job.
2. `Dispatcher` получает инструмент из `Registry` по имени операции (`extract_text` или `text_statistics`).
3. `Dispatcher` вызывает `Tool.execute(input)`.
4. Инструмент вызывает `DocumentReader.read(document_ref)`.
5. Инструмент формирует единый `ToolResult`.
6. `Dispatcher` возвращает `ToolResult` вызывающему компоненту. `JobService` сохраняет успешный результат и переводит Job в `done`; при ошибке сохраняет ошибку и переводит Job в `failed`.

Допустимые состояния Job определены в `docs/architecture.md`: `created`, `running`, `done`, `failed`. Инструменты не изменяют состояние Job и не обращаются к HTTP API.

## 3. Общий интерфейс Tool

Каждый инструмент должен реализовывать один и тот же интерфейс:

```python
class Tool(Protocol):
    name: str

    def execute(self, input: ToolInput) -> ToolResult:
        ...
```

### 3.1. ToolInput

`ToolInput` — внутренний объект, который Dispatcher передаёт инструменту. Файл уже сохранён в хранилище; инструмент получает ссылку на него, а не HTTP-загрузку или содержимое multipart-запроса.

| Поле | Тип | Обязательность | Описание |
|---|---|---:|---|
| `job_id` | `str` | да | Идентификатор Job для логирования и диагностики. |
| `document_ref` | `str` | да | Непрозрачная ссылка/идентификатор документа в хранилище. |
| `filename` | `str` | да | Исходное имя файла; не использовать как путь к файлу. |
| `media_type` | `str` | да | Определённый при приёме тип файла: `application/pdf` или `text/plain`. |
| `options` | `dict[str, object]` | да | Параметры конкретной операции; в MVP пустой объект `{}`. |

Пример:

```json
{
  "job_id": "8f6d6d7a-9f9a-4b85-9e6d-4e9f8d7c1a20",
  "document_ref": "documents/8f6d6d7a-9f9a-4b85-9e6d-4e9f8d7c1a20",
  "filename": "report.pdf",
  "media_type": "application/pdf",
  "options": {}
}
```

`document_ref` является внутренней ссылкой. Публичный API не должен раскрывать физический путь хранения.

## 4. Единый ToolResult

Каждый инструмент возвращает `ToolResult` одного из двух видов.

### Успех

```json
{
  "ok": true,
  "data": {
    "text": "Example document text",
    "page_count": 2,
    "format": "pdf"
  },
  "error": null
}
```

### Ошибка

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "DOCUMENT_CORRUPTED",
    "message": "The PDF document is damaged or cannot be parsed.",
    "details": []
  }
}
```

Структура:

| Поле | Тип | Описание |
|---|---|---|
| `ok` | `bool` | Признак успешного выполнения. |
| `data` | `object \| null` | Данные успешного результата; при ошибке `null`. |
| `error` | `ToolError \| null` | Ошибка; при успехе `null`. |

Инварианты:

- при `ok = true`: `data` заполнено, `error = null`;
- при `ok = false`: `data = null`, `error` заполнено;
- Tool не возвращает HTTP-коды и не формирует HTTP-ответы;
- Tool не меняет состояние Job и не сохраняет Job самостоятельно.

### 4.1. ToolError

| Поле | Тип | Описание |
|---|---|---|
| `code` | `str` | Машиночитаемый код ошибки. |
| `message` | `str` | Краткое описание ошибки для диагностики. |
| `details` | `list[ErrorDetail]` | Дополнительные сведения; пустой список, если деталей нет. |

`ErrorDetail`:

```json
{
  "field": "options",
  "issue": "Unknown option: language"
}
```

Внутренние ошибки инструментов должны использовать те же коды предметной области, которые JobService сохраняет в Job. HTTP API преобразует их в единый публичный формат ошибки.

## 5. DocumentReader

### 5.1. Ответственность

`DocumentReader` предоставляет общий способ чтения PDF и TXT и скрывает от инструментов детали работы с PyMuPDF, декодирования UTF-8 и физического хранения файла.

Интерфейс:

```python
class DocumentReader(Protocol):
    def read(self, document_ref: str) -> DocumentReadResult:
        ...
```

`DocumentReadResult`:

| Поле | Тип | Описание |
|---|---|---|
| `text` | `str` | Извлечённый текст документа. |
| `page_count` | `int \| None` | Число страниц PDF; для TXT — `None`. |
| `format` | `Literal["pdf", "txt"]` | Фактически прочитанный формат. |

Пример:

```json
{
  "text": "Example document text",
  "page_count": 2,
  "format": "pdf"
}
```

Правила чтения:

- TXT декодируется как UTF-8.
- PDF читается только при наличии текстового слоя.
- OCR не выполняется.
- Для TXT `page_count` равен `null`.
- Для PDF `page_count` содержит число страниц.
- `DocumentReader` не подсчитывает слова и символы — это ответственность `TextStatisticsTool`.

## 6. Инструменты MVP

### 6.1. ExtractTextTool

- `name`: `extract_text`
- Вход: общий `ToolInput`; `options` в MVP должен быть пустым.
- Чтение: `DocumentReader.read(input.document_ref)`.
- Успешный `data`:

```json
{
  "text": "Extracted document text",
  "page_count": 2,
  "format": "pdf"
}
```

Для TXT `page_count` равен `null`, `format` равен `txt`.

Ошибки:

- `UNSUPPORTED_FORMAT` — формат не поддерживается (обычно должен быть отклонён ещё на этапе HTTP-приёма; код оставлен для защитной проверки чтения);
- `DOCUMENT_CORRUPTED` — PDF повреждён или не может быть разобран;
- `TEXT_NOT_FOUND` — документ прочитан, но извлекаемого текста нет;
- `DOCUMENT_READ_FAILED` — другая ошибка чтения или доступа к сохранённому документу.

### 6.2. TextStatisticsTool

- `name`: `text_statistics`
- Вход: общий `ToolInput`; `options` в MVP должен быть пустым.
- Чтение: `DocumentReader.read(input.document_ref)`.
- Успешный `data`:

```json
{
  "word_count": 120,
  "character_count": 845,
  "page_count": 2
}
```

`page_count` равен `null` для TXT.

**Предлагаемые правила подсчёта для однозначного тестирования (требуют подтверждения команды):**

- `word_count` — количество непустых последовательностей символов, разделённых пробельными символами (аналог `text.split()`).
- `character_count` — количество Unicode code points в извлечённой строке, включая пробелы и переводы строк.
- `page_count` — количество страниц PDF, предоставленное `DocumentReader`; для TXT — `null`.

Ошибки:

- `UNSUPPORTED_FORMAT`;
- `DOCUMENT_CORRUPTED`;
- `TEXT_NOT_FOUND`;
- `DOCUMENT_READ_FAILED`.

Правила подсчёта не должны дублироваться в `DocumentReader`: он только читает документ и возвращает текст и число страниц.

## 7. Ответственность за валидацию

Проверки распределяются между компонентами, чтобы одна и та же логика не дублировалась на нескольких уровнях.

| Компонент | Что проверяет |
|---|---|
| HTTP API | Наличие файла и операции, корректность multipart-запроса, допустимый размер и поддерживаемый формат на этапе приёма. Неподдерживаемый формат отклоняется до создания Job. |
| JobService | Правила создания Job, ключ идемпотентности, допустимость операции и переходов состояния Job. |
| Dispatcher / Registry | Наличие зарегистрированного инструмента для имени операции. |
| Конкретный Tool | Наличие и корректность параметров своей операции (`options`). |
| DocumentReader | Доступность документа по `document_ref`, фактическая возможность прочитать PDF/TXT, корректность PDF и декодирования TXT. |

Неподдерживаемый формат отклоняется до создания Job с `UNSUPPORTED_FORMAT`. Повреждённый PDF выявляется при выполнении Tool: Job уже находится в `running`, после чего JobService сохраняет ошибку и переводит её в `failed`. Отсутствие извлекаемого текста приводит к `TEXT_NOT_FOUND` и тому же переходу `running → failed`.

## 8. Коды ошибок Tool

| Код | Значение | Где возникает |
|---|---|---|
| `UNSUPPORTED_FORMAT` | Формат не поддерживается. | Защитная проверка DocumentReader; публичный API обычно отклоняет файл раньше. |
| `DOCUMENT_CORRUPTED` | PDF повреждён или не может быть разобран. | DocumentReader. |
| `TEXT_NOT_FOUND` | В документе нет извлекаемого текста. | Tool после чтения через DocumentReader. |
| `DOCUMENT_READ_FAILED` | Документ недоступен или произошла другая ошибка чтения. | DocumentReader. |

Ошибки жизненного цикла Job, например `INVALID_JOB_TRANSITION` и `WORKER_INTERRUPTED`, не являются ошибками Tool: ими управляет JobService / JobRunner.

### 8.1. Ошибки уровня JobRunner

Инструмент возвращает только осмысленные ошибки из таблицы выше. Ситуации, когда `execute` падает с неожиданным исключением или не возвращает управление, обрабатывает `JobRunner` (см. [ADR-0002](adr/0002-async-jobs.md), п. 4):

| Код | Значение | Где возникает |
|---|---|---|
| `INTERNAL_ERROR` | Tool завершился неожиданным исключением, которое не является `ToolResult.error`. | JobRunner перехватывает исключение и переводит Job `running → failed`. |
| `PROCESSING_TIMEOUT` | Tool не вернул управление за отведённое время (предлагаемый лимит — 60 секунд). | JobRunner ограничивает время выполнения и переводит Job `running → failed`. |

Оба кода сохраняются в `Job.error` и видны клиенту через `GET /jobs/{job_id}` и `GET /jobs/{job_id}/result`. Tool не должен сам возвращать `INTERNAL_ERROR` или `PROCESSING_TIMEOUT` в `ToolResult.error`: если инструмент способен диагностировать проблему, он использует коды из раздела 8.

## 9. Ограничения MVP

- Одна Job обрабатывает один документ и одну операцию.
- Поддерживаются PDF с текстовым слоем и TXT в UTF-8.
- OCR, LLM и массовая обработка не входят в MVP.
- Tool не знает о HTTP, базе данных и конкретном механизме фонового запуска.
- Оба обязательных инструмента используют общий `DocumentReader`.
