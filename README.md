## VibeEvent
Сервис записи и контроля документов: сроки, статусы, напоминания.

### Возможности
- Добавление документа с датой окончания и типом
- Список документов, истекающих в ближайшие 30/60 дней
- Обновление документа с новой датой окончания и историей изменений
- Механизм напоминаний (email/webhook) на тестовый адрес

### Быстрый старт
1) Установить зависимости:
```
pip install -r requirements.txt
```

2) Запустить API:
```
python -m app.main
```

API будет доступно на `http://127.0.0.1:8000`.
UI доступен на `http://127.0.0.1:8000/`.

### Краткое руководство
1) Добавьте документ через кнопку `+ Добавить документ`.
2) Используйте поиск и фильтры карточек по срокам.
3) Нажмите `Продлить`, чтобы обновить срок действия.
4) Нажмите `История`, чтобы увидеть историю обновлений.
5) Выберите режим напоминаний и при необходимости укажите email/URL.
6) Кнопка `Удалить` удаляет один документ, `Очистить все` — все документы.

### Напоминания через UI
В верхней панели доступны поля:
- `Режим напоминаний` — `Email` или `Webhook`
- `Цель` — email адрес или URL (опционально)

Если цель не указана, используется значение из переменных окружения.

### Примеры запросов
Добавить документ:
```
POST /documents
{
  "title": "Паспорт",
  "doc_type": "passport",
  "expiry_date": "2026-12-31"
}
```

Список документов:
```
GET /documents
```

Документы с истечением в 30/60 дней:
```
GET /documents/expiring?days=30
GET /documents/expiring?days=60
```

Обновить документ с новой датой:
```
POST /documents/{id}/renew
{
  "new_expiry_date": "2028-12-31"
}
```

История обновлений:
```
GET /documents/{id}/history
```

Отправка напоминаний (тестовый email/webhook):
```
POST /reminders/send?days=30&mode=email
POST /reminders/send?days=60&mode=webhook
```

Отправка напоминаний на конкретную цель:
```
POST /reminders/send?days=30&mode=email&target=test@example.com
POST /reminders/send?days=60&mode=webhook&target=https://example.com/hook
```

Если не указан `SMTP_HOST`, напоминания пишутся в `data/outbox.log`.

### Настройка тестовых адресов
- `REMINDER_TEST_EMAIL` — тестовый email (по умолчанию `test@example.com`)
- `REMINDER_WEBHOOK_URL` — тестовый webhook URL (по умолчанию `https://example.invalid/webhook`)

### SMTP для реальной отправки писем
Если указан `SMTP_HOST`, сервис будет отправлять email через SMTP.

- `SMTP_HOST` — адрес SMTP сервера
- `SMTP_PORT` — порт (по умолчанию `587`)
- `SMTP_USER` — логин (опционально)
- `SMTP_PASSWORD` — пароль (опционально)
- `SMTP_FROM` — адрес отправителя (по умолчанию `SMTP_USER` или `no-reply@localhost`)
- `SMTP_TLS` — включить STARTTLS (`true`/`false`, по умолчанию `true`)
- `SMTP_SSL` — использовать SMTP over SSL (`true`/`false`, по умолчанию `false`)
- `SMTP_DISABLED` — принудительно отключить SMTP (например, для тестов)

Пример `.env`:
```
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=mailer@example.com
SMTP_PASSWORD=secret
SMTP_FROM=mailer@example.com
SMTP_TLS=true
SMTP_SSL=false
```

### Безопасность и защита от спама
Включено ограничение частоты запросов (rate limit) по IP:
- `RATE_LIMIT_DOCUMENTS` — лимит запросов к документам в минуту (по умолчанию `200`)
- `RATE_LIMIT_REMINDERS` — лимит отправки напоминаний в минуту (по умолчанию `20`)

Если лимит превышен, сервер вернет `429 Too Many Requests`.

### UI автотесты (Playwright, Python)
1) Установить зависимости:
```
pip install -r requirements.txt
```

2) Установить браузеры:
```
python -m playwright install
```

3) Запустить тесты:
```
pytest tests
```

