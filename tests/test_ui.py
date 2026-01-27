"""UI автотесты Playwright для сервиса документов."""

import json
import re
import socket
import subprocess
import time

import pytest
from playwright.sync_api import expect

BASE_URL = "http://127.0.0.1:8000"


def wait_for_health(timeout_seconds: int = 20) -> None:
    """Ожидает, когда API станет доступным."""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 8000), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("API не поднялся за отведенное время")


@pytest.fixture(scope="session", autouse=True)
def server():
    """Поднимает сервер для UI тестов и гасит его по окончании."""
    try:
        wait_for_health(timeout_seconds=2)
        yield
        return
    except RuntimeError:
        pass

    process = subprocess.Popen(["py", "-m", "app.main"])
    wait_for_health()
    yield
    process.terminate()
    process.wait(timeout=10)


def build_title(prefix: str) -> str:
    """Генерирует уникальное имя документа."""
    return f"{prefix} {int(time.time() * 1000)}"


def add_days(days: int) -> str:
    """Возвращает дату через N дней в ISO формате."""
    return time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 86400))


def wait_for_api(page) -> None:
    """Открывает UI и проверяет доступность API."""
    page.goto("/")
    expect(page.locator("#apiStatus")).to_contain_text("доступно")


class TestDocumentForm:
    """Тесты формы добавления документа."""

    def test_add_document(self, page):
        """Проверяет создание документа через UI."""
        wait_for_api(page)
        title = build_title("Паспорт")
        page.click("#openAddModal")
        page.fill('input[name="title"]', title)
        page.fill('input[name="doc_type"]', "Паспорт")
        page.fill('input[name="expiry_date"]', "2026-12-31")
        page.click('button[type="submit"]')
        expect(page.locator("#addMessage")).to_contain_text("Документ добавлен")
        expect(page.locator("#documentsGrid")).to_contain_text(title)

    def test_add_form_validation(self, page):
        """Проверяет валидацию обязательных полей формы."""
        wait_for_api(page)
        page.click("#openAddModal")
        page.click('button[type="submit"]')
        form = page.locator("#addForm")
        expect(form.locator('input[name="title"]')).to_be_focused()
        expect(page.locator("#addMessage")).not_to_contain_text("Документ добавлен")

    def test_add_form_invalid_date(self, page):
        """Проверяет отказ при некорректной дате."""
        wait_for_api(page)
        page.click("#openAddModal")
        page.fill('input[name="title"]', build_title("Паспорт"))
        page.fill('input[name="doc_type"]', "Паспорт")
        page.evaluate(
            """
            () => {
                const input = document.querySelector('input[name="expiry_date"]');
                input.type = "text";
                input.value = "2026-99-31";
            }
            """
        )
        page.click('button[type="submit"]')
        expect(page.locator("#addMessage")).to_contain_text("Некорректная дата")

    def test_add_modal_close(self, page):
        """Проверяет закрытие модального окна формы."""
        wait_for_api(page)
        page.click("#openAddModal")
        expect(page.locator("#addModal")).to_have_class(re.compile(r"\bopen\b"))
        page.click('.modal-close[data-close="addModal"]')
        expect(page.locator("#addModal")).not_to_have_class(re.compile(r"\bopen\b"))


class TestFiltersAndSearch:
    """Тесты фильтров и поиска по документам."""

    def test_expiring_lists(self, page):
        """Проверяет фильтры 30 и 30–60 дней."""
        title_30 = build_title("Страховка 30")
        title_60 = build_title("Страховка 60")
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title_30, "doc_type": "Страховка", "expiry_date": add_days(20)}
            ),
            headers={"Content-Type": "application/json"},
        )
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title_60, "doc_type": "Страховка", "expiry_date": add_days(50)}
            ),
            headers={"Content-Type": "application/json"},
        )

        wait_for_api(page)
        page.click('[data-filter="soon"]')
        expect(page.locator("#documentsGrid")).to_contain_text(title_30)
        expect(page.locator("#documentsGrid")).not_to_contain_text(title_60)

        page.click('[data-filter="mid"]')
        expect(page.locator("#documentsGrid")).to_contain_text(title_60)
        expect(page.locator("#documentsGrid")).not_to_contain_text(title_30)

    def test_search_by_title(self, page):
        """Проверяет поиск по названию документа."""
        title = build_title("Загранпаспорт")
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Паспорт", "expiry_date": add_days(200)}
            ),
            headers={"Content-Type": "application/json"},
        )
        wait_for_api(page)
        page.fill("#searchInput", title)
        expect(page.locator("#documentsGrid")).to_contain_text(title)
        page.fill("#searchInput", "несуществующий")
        expect(page.locator("#documentsGrid")).not_to_contain_text(title)

    def test_stat_filters_expired_active(self, page):
        """Проверяет фильтры истекших и активных документов."""
        expired_title = build_title("Истекший")
        active_title = build_title("Активный")
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": expired_title, "doc_type": "Тест", "expiry_date": add_days(-3)}
            ),
            headers={"Content-Type": "application/json"},
        )
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": active_title, "doc_type": "Тест", "expiry_date": add_days(120)}
            ),
            headers={"Content-Type": "application/json"},
        )
        wait_for_api(page)
        page.click('[data-filter="expired"]')
        expect(page.locator("#documentsGrid")).to_contain_text(expired_title)
        expect(page.locator("#documentsGrid")).not_to_contain_text(active_title)
        page.click('[data-filter="active"]')
        expect(page.locator("#documentsGrid")).to_contain_text(active_title)
        expect(page.locator("#documentsGrid")).not_to_contain_text(expired_title)

    def test_refresh_button(self, page):
        """Проверяет кнопку обновления списка."""
        title = build_title("Обновление")
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Тест", "expiry_date": add_days(40)}
            ),
            headers={"Content-Type": "application/json"},
        )
        wait_for_api(page)
        page.click("#refreshButton")
        expect(page.locator("#documentsGrid")).to_contain_text(title)


class TestRenewAndHistory:
    """Тесты продления документа и истории."""

    def test_renew_and_history(self, page):
        """Проверяет продление документа и отображение истории."""
        title = build_title("Права")
        expiry_date = add_days(10)
        response = page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Права", "expiry_date": expiry_date}
            ),
            headers={"Content-Type": "application/json"},
        )
        document_id = response.json()["id"]
        new_expiry = add_days(400)

        wait_for_api(page)
        expect(page.locator("#documentsGrid")).to_contain_text(title)
        page.fill(f'input[data-renew="{document_id}"]', new_expiry)
        page.click(f'button[data-renew-button="{document_id}"]')
        page.click(f'button[data-history-button="{document_id}"]')
        expect(page.locator("#historyList")).to_contain_text(
            f"Документ #{document_id}"
        )

    def test_renew_invalid_date(self, page):
        """Проверяет отказ при некорректной дате продления."""
        title = build_title("Некорректная дата")
        response = page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Тест", "expiry_date": add_days(10)}
            ),
            headers={"Content-Type": "application/json"},
        )
        document_id = response.json()["id"]
        wait_for_api(page)
        page.evaluate(
            """
            (docId) => {
                const input = document.querySelector(`input[data-renew="${docId}"]`);
                input.type = "text";
                input.value = "2026-99-31";
            }
            """,
            document_id,
        )
        page.click(f'button[data-renew-button="{document_id}"]')
        expect(page.locator("#toast")).to_contain_text("Некорректная дата")

    def test_history_modal_close(self, page):
        """Проверяет закрытие модального окна истории."""
        title = build_title("Сертификат")
        response = page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Сертификат", "expiry_date": add_days(90)}
            ),
            headers={"Content-Type": "application/json"},
        )
        document_id = response.json()["id"]
        wait_for_api(page)
        page.click(f'button[data-history-button="{document_id}"]')
        expect(page.locator("#historyModal")).to_have_class(re.compile(r"\bopen\b"))
        page.click('.modal-close[data-close="historyModal"]')
        expect(page.locator("#historyModal")).not_to_have_class(
            re.compile(r"\bopen\b")
        )


class TestReminders:
    """Тесты отправки напоминаний."""

    def test_send_reminders(self, page):
        """Проверяет отправку напоминаний через UI."""
        wait_for_api(page)
        page.click("#reminderButton")
        expect(page.locator("#toast")).to_contain_text("Отправлено")


class TestDeletion:
    """Тесты удаления документов."""

    def test_delete_document(self, page):
        """Проверяет удаление документа через UI."""
        title = build_title("Удаление")
        response = page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": title, "doc_type": "Тест", "expiry_date": add_days(120)}
            ),
            headers={"Content-Type": "application/json"},
        )
        document_id = response.json()["id"]
        wait_for_api(page)
        expect(page.locator("#documentsGrid")).to_contain_text(title)
        page.on("dialog", lambda dialog: dialog.accept())
        page.click(f'button[data-delete-button="{document_id}"]')
        expect(page.locator("#documentsGrid")).not_to_contain_text(title)

    def test_clear_all_documents(self, page):
        """Проверяет кнопку очистки всех документов."""
        page.context.request.post(
            "/documents",
            data=json.dumps(
                {"title": build_title("Очистка"), "doc_type": "Тест", "expiry_date": add_days(15)}
            ),
            headers={"Content-Type": "application/json"},
        )
        wait_for_api(page)
        page.on("dialog", lambda dialog: dialog.accept())
        page.click("#clearAllButton")
        expect(page.locator("#toast")).to_contain_text("Удалено документов")
