# CRM-интеграции Call-Pilot

## Как устроена доставка

1. Оператор подтверждает карточку в HITL.
2. `CallStore.confirm_call` вызывает `service.enqueue_crm`.
3. Карточка попадает в durable-outbox `data/crm_outbox.db`.
4. `OutboxDispatcher` восстанавливает из PII-vault только разрешённые поля клиента (имя, телефон, email) и отправляет карточку в CRM.
5. При ошибке попытка повторяется; при 4xx — фиксируется ошибка.

Карточка уходит в CRM только после подтверждения человеком.

Резюме и QA-цитаты остаются маскированными: в комментарии CRM могут встречаться токены вида `[PERSON_1]`. Это осознанная защита — полные персональные данные передаются только в разрешённых полях клиента (имя, телефон, email).

Доставка работает по принципу **at-least-once**: если CRM приняла лид, но ответ потерялся, повторная попытка может создать дубль. Для пилота это допустимо; в production нужно добавить проверку по `ORIGIN_ID` / Call-Pilot ID или идемпотентный ключ на стороне CRM.

## Bitrix24

Поддерживается inbound webhook, без OAuth-приложения.

### Настройка портала

1. Bitrix24 → Приложения → Вебхуки → Входящий вебхук.
2. Выдайте право `crm`.
3. Скопируйте URL вида:

```text
https://<portal>.bitrix24.ru/rest/<user_id>/<token>/
```

### `.env`

```text
CRM_ENABLED=true
CRM_PROVIDER=bitrix24
CRM_BITRIX24_WEBHOOK_URL=https://<portal>.bitrix24.ru/rest/<user_id>/<token>/
CRM_BITRIX24_ENTITY=lead
CRM_BITRIX24_SOURCE_ID=
CRM_BITRIX24_ASSIGNED_BY_ID=0
```

`CRM_BITRIX24_ENTITY` — `lead` или `deal`.

### Что создаётся

Метод `crm.lead.add` или `crm.deal.add` с полями:

- `TITLE` — «Звонок · Клиент · #ID»;
- `NAME` — имя клиента;
- `PHONE`, `EMAIL` — контактные данные;
- `COMMENTS` — резюме, следующий шаг, QA-score, top-3 critical/high, эскалация, Call-Pilot ID;
- `ORIGINATOR_ID=call-pilot`, `ORIGIN_ID=<request_id>`;
- опционально `SOURCE_ID`, `ASSIGNED_BY_ID`.

### Кастомные поля

```text
CRM_FIELD_MAP={"qa_score":"UF_CRM_1712345678","summary":"UF_CRM_1712345679"}
```

Ключи — поля payload Call-Pilot (`qa_score`, `summary`, `next_action`, `request_id`, `status`). Значения — коды полей Bitrix24.

### Проверка

```bash
python -m app.cli outbox
```

Команда берёт pending-записи из outbox и отправляет их в Bitrix24.

## amoCRM

Поддерживается API v4 с долгоживущим токеном.

### Настройка интеграции

1. amoCRM → Настройки → Интеграции → Создать интеграцию.
2. Выдайте доступ к сделкам, контактам и примечаниям.
3. Получите долгоживущий токен.

### `.env`

```text
CRM_ENABLED=true
CRM_PROVIDER=amo
CRM_AMO_BASE_URL=https://<subdomain>.amocrm.ru
CRM_AMO_TOKEN=<long-lived-token>
CRM_AMO_PIPELINE_ID=0
CRM_AMO_STATUS_ID=0
CRM_AMO_RESPONSIBLE_USER_ID=0
```

`CRM_AMO_PIPELINE_ID`, `CRM_AMO_STATUS_ID`, `CRM_AMO_RESPONSIBLE_USER_ID` опциональны: `0` означает «не передавать».

### Что создаётся

`POST /api/v4/leads/complex` создаёт сделку и контакт одним запросом:

- название сделки: «Звонок: Клиент · #ID»;
- контакт: имя, телефон, email;
- опционально воронка, этап и ответственный.

После создания сделки добавляется примечание `common` с резюме, следующим шагом, QA-score, нарушениями и Call-Pilot ID.

Если примечание не добавилось, сделка всё равно считается созданной — повтор не делается, чтобы не дублировать запись.

### Кастомные поля

В amoCRM указываются **числовые ID** полей:

```text
CRM_FIELD_MAP={"qa_score":123456,"summary":123457,"next_action":123458}
```

ID можно найти в настройках поля или через `GET /api/v4/leads/custom_fields`.

### Проверка

```bash
python -m app.cli outbox
```

## Универсальный webhook

Старый режим сохранён:

```text
CRM_ENABLED=true
CRM_PROVIDER=webhook
CRM_WEBHOOK_URL=https://crm.example/webhook
CRM_WEBHOOK_SECRET=<secret>
```

Запрос подписывается `X-Webhook-Signature` (HMAC-SHA256 от тела).

## Запуск доставки

Outbox не отправляется сам по себе. Запускайте команду по cron или systemd timer:

```bash
cd /opt/callpilot
.venv/bin/python -m app.cli outbox
```

Пример cron:

```text
* * * * * cd /opt/callpilot && .venv/bin/python -m app.cli outbox >> /var/log/callpilot-crm.log 2>&1
```

Вариант systemd timer:

```ini
# /etc/systemd/system/callpilot-crm.service
[Unit]
Description=Call-Pilot CRM outbox dispatcher

[Service]
Type=oneshot
WorkingDirectory=/opt/callpilot
ExecStart=/opt/callpilot/.venv/bin/python -m app.cli outbox
User=callpilot
```

```ini
# /etc/systemd/system/callpilot-crm.timer
[Unit]
Description=Run Call-Pilot CRM dispatcher every minute

[Timer]
OnBootSec=30
OnUnitActiveSec=60

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now callpilot-crm.timer
```

`CRM_DISPATCH_INTERVAL_SECONDS` используется планировщиком, но обработчик `crm_dispatch` в worker пока не подключён. Для пилота используйте cron/outbox-команду.

## Безопасность

- Токены и вебхук-URL хранятся только в `.env`, не в Git и не в логах.
- Bitrix24/amoCRM требуют HTTPS.
- В CRM уходят только разрешённые поля клиента; резюме и QA-цитаты остаются в маскированном виде.
- Перед production проверьте интеграцию на тестовом портале/аккаунте.

## Частые ошибки

| Ошибка | Что проверить |
|---|---|
| `401` / `403` | токен amoCRM, права вебхука Bitrix24 |
| `400` | коды полей Bitrix24 или ID полей amoCRM в `CRM_FIELD_MAP` |
| `429` | лимит запросов; адаптер повторяет попытку |
| Дубли лидов | ответ потерялся после создания; проверьте `ORIGIN_ID` / Call-Pilot ID |
| Нет отправки | `CRM_ENABLED=true`, `CRM_PROVIDER`, запуск `app.cli outbox` |
