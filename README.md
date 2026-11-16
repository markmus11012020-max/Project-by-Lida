Call-Pilot — выпускной проект
AI-постобработка и контроль качества звонков для колл-центров

1. Что это

Call-Pilot принимает звонок, расшифровывает его, собирает карточку,
проверяет качество по 10 критериям и отдаёт менеджеру только исключения.
AI пишет черновик, оператор подтверждает, CRM получает финальную версию.

Проект решает понятную задачу: QA слушает 2–5% звонков, оператор тратит
3–4 минуты на постобработку, а жалобы и нарушения всплывают постфактум.
Call-Pilot проверяет 100% звонков и сохраняет прозрачный аудит.

2. Быстрый запуск за 10 минут

2.1. Создайте окружение и установите зависимости.

Windows PowerShell:

    python -m venv .venv
    .venv\Scripts\python.exe -m pip install -r requirements.txt

Linux или macOS:

    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt

2.2. Создайте .env из .env.example.

Windows:

    copy .env.example .env

Linux или macOS:

    cp .env.example .env

Укажите AITUNNEL_API_KEY. Остальные значения можно оставить по умолчанию.
Для локального запуска DEMO_MODE=false, чтобы работали API-создание и обработка.

2.3. Запустите приложение из папки call-center.

Windows:

    cd call-center
    ..\.venv\Scripts\python.exe -m uvicorn call_center_app:app --host 127.0.0.1 --port 8020

Linux или macOS:

    cd call-center
    ../.venv/bin/python -m uvicorn call_center_app:app --host 127.0.0.1 --port 8020

Откройте:

    http://127.0.0.1:8020/            лендинг
    http://127.0.0.1:8020/dashboard   обзор звонков
    http://127.0.0.1:8020/qa          QA-аналитика
    http://127.0.0.1:8020/audit       журнал аудита

3. Docker

    docker build -t callpilot .
    docker run --rm -p 8020:8020 --env-file .env callpilot

Dockerfile запускает именно веб-панель Call-Pilot на порту 8020.
Для сохранения SQLite между перезапусками подключите volume на
/app/call-center/data.

4. Три точки API

Примеры ниже для Windows cmd. В Linux и macOS замените символ ^
на обратный слэш.

4.1. Создать звонок.

    curl -X POST http://127.0.0.1:8020/api/v1/calls ^
      -H "Content-Type: application/json" ^
      -d "{\"title\":\"Тестовый звонок\",\"transcript\":\"Оператор: Здравствуйте, компания Ромашка. Клиент: Не пришла доставка заказа 12345. Оператор: Проверю статус и перезвоню.\",\"client\":\"Анна\",\"operator\":\"Дмитрий\"}"

Ответ содержит call_id. Это точка создания сущности в базе.

4.2. Получить список звонков.

    curl "http://127.0.0.1:8020/api/v1/calls?source=api"

Каждый элемент содержит need_review, review_reason, qa_score и статус.

4.3. Запустить AI-обработку.

    curl -X POST http://127.0.0.1:8020/api/v1/calls/api_XXXXXXXXXX/process

API предназначен для локального теста и пилота. Не отправляйте в него
реальные персональные данные без согласия и настройки хранения.

Вместо api_XXXXXXXXXX подставьте call_id из первого ответа.
Ответ содержит строгий JSON карточки, qa_score, need_review и review_reason.

Дополнительно:

    curl "http://127.0.0.1:8020/api/v1/calls/api_XXXXXXXXXX"
    curl "http://127.0.0.1:8020/api/v1/audit?limit=20"
    curl -o results.csv http://127.0.0.1:8020/export/results.csv
    curl -o audit.jsonl http://127.0.0.1:8020/export/audit.jsonl

5. Ручная проверка

После AI-обработки сервис выставляет need_review=true, если:

1. Есть critical или high нарушение.
2. QA-score ниже 85.
3. Клиент негативен, а тема — жалоба или возврат.
4. Модель не уверена или просит эскалацию.
5. В ответе нет критичных полей.

В этом случае review_reason объясняет причину, а звонок попадает в
очередь ручной проверки. Оператор открывает карточку, слушает аудио,
исправляет поля и подтверждает финальную версию. Только после этого
результат уходит в CRM.

6. Данные и аудит

SQLite: call-center/data/call_center.db

Основные таблицы:

    demo_calls       звонки, транскрипт, источник, аудио
    call_reviews     статус проверки, need_review, review_reason, правки
    audit_runs       action, input, output, status, error, duration_ms, created_at
    leads            заявки с лендинга

Дополнительно движок ведёт processing_log и business_results.
Аудио демо лежит в call-center/static/audio. Реальные записи — в
call-center/data/audio в зашифрованном виде.

Журнал аудита доступен на /audit и через /api/v1/audit.
Экспорт: /export/results.csv и /export/audit.jsonl.

7. Тестовые данные

Файл: tests_data/inputs.jsonl

10 кейсов, из них 5 asserted с need_review=true, включая 2 critical;
остальные 5 информационные. Результат последнего прогона: 5/5 asserted.
Запуск при работающем приложении:

    .venv\Scripts\python.exe call-center\scripts\run_tests_data.py --strict

Скрипт создаёт звонки через API, запускает обработку, сравнивает
ожидаемый и фактический need_review и пишет tests_data/last_run.json.
Сводка последнего прогона: docs/test_run_summary.md.

8. Веб-панель

Минимум три экрана:

    /dashboard   список звонков, KPI, очередь ручной проверки
    /calls/{id}  карточка: аудио, транскрипт, QA, HITL-подтверждение
    /qa          QA-аналитика: покрытие, auto-pass, нарушения
    /audit       журнал действий и ошибок

9. Демо и защита

Демо-видео: call-center/demo/callpilot-demo.mp4, 2 минуты 25 секунд.
Защита: call-center/demo/callpilot-defense.mp4, 5 минут 34 секунды (темп +15%).
Видео не коммитятся в Git; приложите файлы к сдаче отдельно.
Сценарий защиты: docs/DEFENSE.md.
Отчёт по шаблону: docs/REPORT.md.
Экономика: docs/economics.txt и блок ROI на лендинге.

10. Проверки

    .venv\Scripts\python.exe -m pytest -q
    .venv\Scripts\python.exe -m scripts.check_readme

11. Ограничения

Публичный демо-стенд работает на DEMO_MODE=true: создание звонков и
AI-обработка через API отключены, чтобы не принимать реальные данные
и не тратить LLM-бюджет. Локально DEMO_MODE=false.

Проект не заменяет оператора: AI готовит черновик, решение принимает
человек. Реальные записи требуют согласия, маскирования ПДн и настройки
хранения по 152-ФЗ.

12. Ссылки

Репозиторий: https://github.com/markmus11012020-max/Project-by-Lida
Публичный демо: https://call-pilot.ru
Кейс «до/после»: https://call-pilot.ru/case
Политика ПДн: https://call-pilot.ru/privacy
Контакт: aillix@mail.ru, +7 962 609-00-01
