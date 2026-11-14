# Демо на 2-3 минуты

## Подготовка

1. В .env вставлен реальный AITUNNEL_API_KEY.
2. Установлены зависимости.
3. Запущен сервер:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

4. Открыты вкладки:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/stats
- http://127.0.0.1:8000/health

5. Для live-прогона заранее выполнен batch:

```powershell
.venv\Scripts\python.exe -m app.cli batch --strict
```

## 0:00-0:20. Проблема

Покажите README или слайд: входящие обращения обрабатываются вручную, на один кейс уходит около шести минут, ошибки не видны, журнала нет.

## 0:20-0:40. Архитектура

Покажите схему из README: вход, LLM, JSON, валидация, эскалация, SQLite, ответ. Подчеркните, что это один конвейер с тремя конфигурациями.

## 0:40-1:20. Сценарий A, поддержка

В Swagger откройте POST /ingest и отправьте:

```json
{
  "scenario": "support",
  "text": "Оплатил заказ №12345, доставки нет. Анна, +7 900 123-45-67."
}
```

Покажите ответ: category delivery, summary, next_action, confidence high, status processed.

## 1:20-1:50. Сценарий B, продажи

Отправьте:

```json
{
  "scenario": "sales",
  "text": "Быстрый заработок! Переходите по ссылке, инвестиции от 1000% в месяц."
}
```

Покажите, что это spam, score 0, status processed, next_action отклонить. Подчеркните: чистый спам не эскалируется, чтобы не грузить менеджера.

## 1:50-2:20. Сценарий C, документы

Отправьте:

```json
{
  "scenario": "documents",
  "text": "ТЗ: разработать Telegram-бота для приёма заявок. Заказчик — ООО Вектор. Срок — 30 дней. Бюджет — 250 000. Нужен приём заявок, уведомления менеджеру, выгрузка в CRM."
}
```

Покажите поля и draft_kp. Подчеркните: цена не выдумана, в черновике стоит «рассчитывается менеджером».

## 2:20-2:40. Эскалация и аудит

Отправьте:

```json
{
  "scenario": "support",
  "text": "Не работает, срочно!"
}
```

Покажите status escalated, confidence low, escalate_reason low_confidence или missing_critical_fields.

Затем откройте:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/audit/ВАШ_REQUEST_ID?include_raw=true" | ConvertTo-Json -Depth 10
```

Покажите, что в журнале есть вход, сырой ответ, статус и ошибка.

## 2:40-3:00. Результаты и экономика

Откройте http://127.0.0.1:8000/stats и покажите:

- total_requests;
- by_status;
- automation_rate;
- total_cost_rub.

Затем покажите CSV live-прогона:

```powershell
Get-Content data/test_run.csv -TotalCount 5
```

Итог: 30 кейсов, около 70 процентов автоматизации, 0 invalid и error, прозрачный аудит. Экономия времени на 30 кейсах — около 69 процентов.

## Команды для проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.check_readme
.venv\Scripts\python.exe -m scripts.economics
```

## Что говорить, если спросят

- Модель: gpt-4o-mini, temperature 0.2, JSON-режим.
- Почему не json_schema: не все модели поддерживают; Pydantic надёжнее.
- Почему SQLite: MVP на одной машине, легко заменить на PostgreSQL.
- Где 60 откликов: шаблоны и трекер в docs, отправка — карьерная часть.
