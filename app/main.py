"""API и UI сервиса контроля документов."""

import os
import smtplib
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.database import get_connection, init_db


def _load_env_file(path: Path) -> None:
    """Загружает переменные окружения из .env, если он есть."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(Path(__file__).resolve().parent.parent / ".env")

app = FastAPI(title="Сервис контроля документов")
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


class DocumentCreate(BaseModel):
    """Входные данные для создания документа."""
    title: str = Field(..., min_length=1, max_length=200)
    doc_type: str = Field(..., min_length=1, max_length=100)
    expiry_date: date


class DocumentOut(BaseModel):
    """Модель ответа для документа."""
    id: int
    title: str
    doc_type: str
    expiry_date: date
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentUpdate(BaseModel):
    """Входные данные для обновления срока документа."""
    new_expiry_date: date


class HistoryOut(BaseModel):
    """Модель ответа для истории обновлений."""
    id: int
    document_id: int
    old_expiry_date: date
    new_expiry_date: date
    updated_at: datetime


class ReminderResult(BaseModel):
    """Модель ответа при отправке напоминаний."""
    sent: int
    mode: str
    target: str
    details: List[str]


def _now() -> datetime:
    """Возвращает текущее время в UTC."""
    return datetime.utcnow()


def _iso_dt(value: datetime) -> str:
    """Форматирует datetime в ISO 8601 с суффиксом Z."""
    return value.replace(microsecond=0).isoformat() + "Z"


def _iso_date(value: date) -> str:
    """Форматирует дату в строку ISO 8601."""
    return value.isoformat()


def _parse_iso_date(value: str) -> date:
    """Парсит дату из строки ISO 8601."""
    return date.fromisoformat(value)


def _parse_iso_dt(value: str) -> datetime:
    """Парсит datetime из строки ISO 8601 с опциональным Z."""
    cleaned = value.rstrip("Z")
    return datetime.fromisoformat(cleaned)


def _document_from_row(row) -> DocumentOut:
    """Преобразует строку из БД в объект ответа документа."""
    return DocumentOut(
        id=row["id"],
        title=row["title"],
        doc_type=row["doc_type"],
        expiry_date=_parse_iso_date(row["expiry_date"]),
        status=row["status"],
        created_at=_parse_iso_dt(row["created_at"]),
        updated_at=_parse_iso_dt(row["updated_at"]),
    )


def _history_from_row(row) -> HistoryOut:
    """Преобразует строку из БД в объект истории обновлений."""
    return HistoryOut(
        id=row["id"],
        document_id=row["document_id"],
        old_expiry_date=_parse_iso_date(row["old_expiry_date"]),
        new_expiry_date=_parse_iso_date(row["new_expiry_date"]),
        updated_at=_parse_iso_dt(row["updated_at"]),
    )


def _write_outbox(message: str) -> None:
    """Записывает сообщение в лог напоминаний."""
    outbox_path = Path(__file__).resolve().parent.parent / "data" / "outbox.log"
    outbox_path.parent.mkdir(parents=True, exist_ok=True)
    with outbox_path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _bool_env(value: Optional[str]) -> bool:
    """Преобразует строковое значение окружения в bool."""
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


_RATE_STATE: dict[tuple[str, str], list[float]] = {}


def _client_ip(request: Request) -> str:
    """Определяет IP клиента для rate limit."""
    return request.client.host if request.client else "unknown"


def _rate_limit(
    request: Request, scope: str, limit: int, window_seconds: int = 60
) -> None:
    """Проверяет лимит запросов на клиента для выбранной области."""
    now = time.time()
    key = (_client_ip(request), scope)
    timestamps = _RATE_STATE.get(key, [])
    fresh = [stamp for stamp in timestamps if now - stamp < window_seconds]
    if len(fresh) >= limit:
        raise HTTPException(status_code=429, detail="Слишком много запросов")
    fresh.append(now)
    _RATE_STATE[key] = fresh


def _send_email(recipient: str, message: str) -> str:
    """Отправляет email через SMTP или пишет в outbox."""
    if _bool_env(os.getenv("SMTP_DISABLED")):
        _write_outbox(f"[EMAIL] to={recipient} {message}")
        return f"email:{recipient}"
    smtp_host = os.getenv("SMTP_HOST")
    if not smtp_host:
        _write_outbox(f"[EMAIL] to={recipient} {message}")
        return f"email:{recipient}"

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@localhost")
    smtp_tls = _bool_env(os.getenv("SMTP_TLS", "true"))
    smtp_ssl = _bool_env(os.getenv("SMTP_SSL", "false"))

    email_message = EmailMessage()
    email_message["From"] = smtp_from
    email_message["To"] = recipient
    email_message["Subject"] = "Напоминание о документе"
    email_message.set_content(message)

    try:
        if smtp_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)

        with server:
            if smtp_tls and not smtp_ssl:
                server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(email_message)
    except smtplib.SMTPException as error:
        raise HTTPException(status_code=500, detail=f"SMTP ошибка: {error}") from error

    _write_outbox(f"[EMAIL:SMTP] to={recipient} {message}")
    return f"email:{recipient}"


def _send_webhook(webhook_url: str, message: str) -> str:
    """Имитирует webhook через запись в outbox."""
    _write_outbox(f"[WEBHOOK] url={webhook_url} {message}")
    return f"webhook:{webhook_url}"


@app.on_event("startup")
def startup() -> None:
    """Инициализирует БД при старте приложения."""
    init_db()


@app.get("/health")
def health() -> dict:
    """Простой health-check для UI и мониторинга."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Отдает главную страницу UI."""
    index_path = static_dir / "index.html"
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.post("/documents", response_model=DocumentOut)
def create_document(payload: DocumentCreate, request: Request) -> DocumentOut:
    """Создает документ с датой окончания и типом."""
    _rate_limit(
        request, "documents", int(os.getenv("RATE_LIMIT_DOCUMENTS", "200"))
    )
    now = _now()
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO documents (title, doc_type, expiry_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payload.title,
                payload.doc_type,
                _iso_date(payload.expiry_date),
                "active",
                _iso_dt(now),
                _iso_dt(now),
            ),
        )
        connection.commit()
        document_id = cursor.lastrowid
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        row = cursor.fetchone()
        return _document_from_row(row)


@app.get("/documents", response_model=List[DocumentOut])
def list_documents() -> List[DocumentOut]:
    """Возвращает список всех документов."""
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM documents ORDER BY expiry_date ASC")
        rows = cursor.fetchall()
        return [_document_from_row(row) for row in rows]


@app.get("/documents/expiring", response_model=List[DocumentOut])
def list_expiring_documents(days: int = Query(30, ge=1, le=365)) -> List[DocumentOut]:
    """Возвращает документы, истекающие в ближайшие N дней."""
    cutoff = date.today() + timedelta(days=days)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT * FROM documents
            WHERE expiry_date <= ?
            ORDER BY expiry_date ASC
            """,
            (_iso_date(cutoff),),
        )
        rows = cursor.fetchall()
        return [_document_from_row(row) for row in rows]


@app.post("/documents/{document_id}/renew", response_model=DocumentOut)
def renew_document(
    document_id: int, payload: DocumentUpdate, request: Request
) -> DocumentOut:
    """Обновляет срок действия документа и пишет историю."""
    _rate_limit(
        request, "documents", int(os.getenv("RATE_LIMIT_DOCUMENTS", "200"))
    )
    now = _now()
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Документ не найден")
        old_expiry = row["expiry_date"]
        cursor.execute(
            """
            UPDATE documents
            SET expiry_date = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (_iso_date(payload.new_expiry_date), "active", _iso_dt(now), document_id),
        )
        cursor.execute(
            """
            INSERT INTO document_history (document_id, old_expiry_date, new_expiry_date, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (document_id, old_expiry, _iso_date(payload.new_expiry_date), _iso_dt(now)),
        )
        connection.commit()
        cursor.execute("SELECT * FROM documents WHERE id = ?", (document_id,))
        updated = cursor.fetchone()
        return _document_from_row(updated)


@app.delete("/documents/{document_id}")
def delete_document(document_id: int, request: Request) -> dict:
    """Удаляет документ и связанную историю обновлений."""
    _rate_limit(
        request, "documents", int(os.getenv("RATE_LIMIT_DOCUMENTS", "200"))
    )
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Документ не найден")
        cursor.execute("DELETE FROM document_history WHERE document_id = ?", (document_id,))
        cursor.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        connection.commit()
    return {"status": "deleted", "id": document_id}


@app.post("/documents/{document_id}/delete")
def delete_document_post(document_id: int, request: Request) -> dict:
    """Удаляет документ через POST для совместимости."""
    return delete_document(document_id, request)


@app.post("/documents/clear")
def clear_documents(request: Request) -> dict:
    """Удаляет все документы и историю обновлений."""
    _rate_limit(
        request, "documents", int(os.getenv("RATE_LIMIT_DOCUMENTS", "200"))
    )
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM documents")
        total = cursor.fetchone()[0]
        cursor.execute("DELETE FROM document_history")
        cursor.execute("DELETE FROM documents")
        connection.commit()
    return {"status": "cleared", "deleted": total}


@app.get("/documents/{document_id}/history", response_model=List[HistoryOut])
def get_document_history(document_id: int) -> List[HistoryOut]:
    """Возвращает историю обновлений по документу."""
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Документ не найден")
        cursor.execute(
            """
            SELECT * FROM document_history
            WHERE document_id = ?
            ORDER BY updated_at DESC
            """,
            (document_id,),
        )
        rows = cursor.fetchall()
        return [_history_from_row(row) for row in rows]


@app.post("/reminders/send", response_model=ReminderResult)
def send_reminders(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    mode: Optional[str] = Query(None, description="email or webhook"),
    target: Optional[str] = Query(None, description="email or webhook target"),
) -> ReminderResult:
    """Отправляет тестовые напоминания по истекающим документам."""
    _rate_limit(
        request, "reminders", int(os.getenv("RATE_LIMIT_REMINDERS", "20"))
    )
    target_mode = (mode or "email").lower()
    if target_mode not in {"email", "webhook"}:
        raise HTTPException(
            status_code=400, detail="Режим должен быть email или webhook"
        )
    cutoff = date.today() + timedelta(days=days)
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT * FROM documents
            WHERE expiry_date <= ?
            ORDER BY expiry_date ASC
            """,
            (_iso_date(cutoff),),
        )
        rows = cursor.fetchall()

    details = []
    if target_mode == "email":
        if target and ("@" not in target or " " in target):
            raise HTTPException(status_code=400, detail="Некорректный email")
        target = target or os.getenv("REMINDER_TEST_EMAIL", "test@example.com")
        smtp_enabled = bool(os.getenv("SMTP_HOST"))
        log_path = str(Path.cwd().joinpath("data", "outbox.log"))
        test_email = target
        for row in rows:
            message = f"Документ {row['title']} истекает {row['expiry_date']}"
            details.append(_send_email(test_email, message))
        target_label = target if smtp_enabled else f"{target} ({log_path})"
        return ReminderResult(
            sent=len(rows), mode="email", target=target_label, details=details
        )

    if target and not target.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Некорректный webhook URL")
    webhook_url = target or os.getenv(
        "REMINDER_WEBHOOK_URL", "https://example.invalid/webhook"
    )
    target = webhook_url
    for row in rows:
        message = f"Документ {row['title']} истекает {row['expiry_date']}"
        details.append(_send_webhook(webhook_url, message))
    return ReminderResult(sent=len(rows), mode="webhook", target=target, details=details)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
