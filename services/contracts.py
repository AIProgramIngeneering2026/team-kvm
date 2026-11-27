
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from core.job import JobStatus


@dataclass(frozen=True, slots=True)
class CreateJobCommand:
    """Данные для создания задания после проверки клиента и чтения файла.

    client_id определяется по проверенному заголовку X-API-Key.
    Его нельзя принимать напрямую из тела HTTP-запроса.

    idempotency_key — необязательный ключ идемпотентности
    согласно контракту OpenAPI из практики 2.

    content содержит содержимое загруженного файла в байтах.
    Максимальный размер файла — 10 МиБ.
    Сервис должен самостоятельно проверить это ограничение.
    """

    client_id: str
    operation: str
    filename: str
    media_type: str
    content: bytes
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    """Представление задания для передачи между сервисом и API.

    result и error содержат данные, которые можно преобразовать в JSON.
    Они не должны содержать SQL-записи или экземпляры ToolError.

    При получении информации о задании API не возвращает result.
    Результат доступен через отдельный эндпоинт /result
    только после перехода задания в состояние done.
    """

    id: str
    operation: str
    status: JobStatus
    filename: str
    created_at: datetime
    updated_at: datetime
    error: dict[str, Any] | None = None
    result: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CreateJobOutcome:
    """Результат создания задания.

    replayed=False — создано новое задание, API возвращает HTTP 202.

    replayed=True — запрос уже выполнялся ранее.
    API возвращает существующее задание с HTTP 200
    и заголовком Idempotency-Replayed: true.
    """

    job: JobSnapshot
    replayed: bool


@dataclass(frozen=True, slots=True)
class JobPage:
    """Страница истории заданий конкретного клиента.

    items — задания текущей страницы.
    limit — максимальное количество заданий на странице.
    offset — количество пропущенных заданий.
    total — общее количество заданий с учётом фильтров,
    но без ограничения limit и offset.
    """

    items: tuple[JobSnapshot, ...]
    limit: int
    offset: int
    total: int


@dataclass(frozen=True, slots=True)
class ErrorDetail:
    """Дополнительная информация об ошибке.

    field — название поля, в котором возникла ошибка.
    issue — описание проблемы.
    """

    field: str
    issue: str


class ServiceError(Exception):
    """Ошибка сервисного слоя с машиночитаемым кодом.

    code — код ошибки для программной обработки.
    message — понятное пользователю описание ошибки.
    details — дополнительная информация о проблемных полях.

    Сервис не определяет HTTP-статус самостоятельно.
    Соответствующий HTTP-статус выбирает слой API.

    Пример:
        ServiceError(
            'JOB_NOT_FOUND',
            'Job was not found.',
            (ErrorDetail('job_id', 'Unknown job.'),)
        )
    """

    def __init__(
        self,
        code: str,
        message: str,
        details: tuple[ErrorDetail, ...] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = tuple(details)


class JobServicePort(Protocol):
    """Интерфейс взаимодействия между API и сервисным слоем.

    Определяет методы, которые должна предоставлять
    конкретная реализация JobService.

    Класс JobService реализует эти методы, но самостоятельно
    определяет внутреннюю логику их выполнения.

    Интерфейс не должен зависеть от FastAPI, HTTPException
    или драйверов базы данных.
    """

    def create_job(self, command: CreateJobCommand) -> CreateJobOutcome:
        """Создать новое задание или вернуть существующее.

        Проверяет входные данные, сохраняет документ и задание
        в состоянии created, обеспечивает идемпотентность.

        Новое задание передаётся на выполнение только после
        успешного завершения транзакции в базе данных.

        При повторном запросе с тем же ключом и содержимым
        возвращается существующее задание без повторного запуска.

        Это правило действует и для заданий в состоянии failed.
        """
        ...

    def get_job(self, *, client_id: str, job_id: str) -> JobSnapshot:
        """Получить задание по идентификатору.

        Возвращает только задание, принадлежащее client_id.

        Если задание не существует или принадлежит другому
        клиенту, вызывает ServiceError с кодом JOB_NOT_FOUND.
        """
        ...

    def list_jobs(
        self,
        *,
        client_id: str,
        status: JobStatus | None = None,
        operation: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> JobPage:
        """Получить историю заданий конкретного клиента.

        Задания сортируются от новых к старым.

        status — необязательный фильтр по состоянию задания.
        operation — необязательный фильтр по типу операции.
        limit — максимальное количество возвращаемых заданий.
        offset — количество записей, которые нужно пропустить.

        Фильтрация выполняется до применения limit и offset.

        Возвращает JobPage с заданиями текущей страницы
        и общим количеством записей, соответствующих фильтрам.
        """
        ...
