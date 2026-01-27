"""Pytest фикстуры для UI тестов."""

import pytest
from playwright.sync_api import sync_playwright

BASE_URL = "http://127.0.0.1:8000"


@pytest.fixture()
def page():
    """Создает страницу в видимом браузере."""
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(base_url=BASE_URL)
        page = context.new_page()
        yield page
        context.close()
        browser.close()
