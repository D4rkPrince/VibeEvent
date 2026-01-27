"""API и UI сервиса контроля документов."""

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.database import get_connection, init_db

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


def _send_email(test_email: str, message: str) -> str:
    """Имитирует отправку email через запись в outbox."""
    _write_outbox(f"[EMAIL] to={test_email} {message}")
    return f"email:{test_email}"


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
def create_document(payload: DocumentCreate) -> DocumentOut:
    """Создает документ с датой окончания и типом."""
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
def renew_document(document_id: int, payload: DocumentUpdate) -> DocumentOut:
    """Обновляет срок действия документа и пишет историю."""
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
def delete_document(document_id: int) -> dict:
    """Удаляет документ и связанную историю обновлений."""
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
def delete_document_post(document_id: int) -> dict:
    """Удаляет документ через POST для совместимости."""
    return delete_document(document_id)


@app.post("/documents/clear")
def clear_documents() -> dict:
    """Удаляет все документы и историю обновлений."""
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
    days: int = Query(30, ge=1, le=365),
    mode: Optional[str] = Query(None, description="email or webhook"),
) -> ReminderResult:
    """Отправляет тестовые напоминания по истекающим документам."""
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
        target = os.getenv("REMINDER_TEST_EMAIL", "test@example.com")
        log_path = str(Path.cwd().joinpath("data", "outbox.log"))
        test_email = target
        for row in rows:
            message = f"Документ {row['title']} истекает {row['expiry_date']}"
            details.append(_send_email(test_email, message))
        return ReminderResult(
            sent=len(rows), mode="email", target=f"{target} ({log_path})", details=details
        )

    webhook_url = os.getenv("REMINDER_WEBHOOK_URL", "https://example.invalid/webhook")
    target = webhook_url
    for row in rows:
        message = f"Документ {row['title']} истекает {row['expiry_date']}"
        details.append(_send_webhook(webhook_url, message))
    return ReminderResult(sent=len(rows), mode="webhook", target=target, details=details)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
