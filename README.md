ПРОЕКТ: АВТОМАТИЗАЦИЯ БИЗНЕС-ПРОЦЕССА С LLM ОТ ВХОДА ДО ДЕЙСТВИЯ

1. ЧТО ЭТО

MVP автоматизирует обработку входящих данных: принимает текст, отправляет его
в LLM, получает строгий JSON, проверяет качество, при необходимости эскалирует
случай человеку и сохраняет бизнес-результат в SQLite.

Проект сделан как учебный кейс URK071 (Zerocoder), но оформлен как небольшой
инженерный продукт: с API, CLI, тестами, аудитом, отчётом и планом развития.

2. ВОЗМОЖНОСТИ

• Три сценария обработки: поддержка, продажи, документы.
• Строгий JSON от LLM и серверная валидация через Pydantic.
• Эскалация при низкой уверенности, нехватке критичных полей и ошибке LLM.
• Журнал аудита: вход, сырой ответ, результат, статус, ошибка, модель, latency.
• Бизнес-результат в SQLite и экспорт в CSV/JSONL.
• Статистика: количество, статусы, автоматизация, стоимость, задержка.
• CLI для одиночной обработки и пакетного прогона 30 тестовых кейсов.
• Детерминированный черновик КП для сценария документов без выдуманных цен.

3. АРХИТЕКТУРА

Клиент (Swagger, curl, CLI)
  -> FastAPI POST /ingest
  -> Реестр сценариев support / sales / documents
  -> Системный промпт и вход в тегах input
  -> AITUNNEL /chat/completions, JSON-режим, temperature 0.2
  -> Разбор JSON и Pydantic-валидация
  -> Контроль качества и эскалация
  -> SQLite: processing_log и business_results
  -> Ответ: статус, бизнес-результат, метаданные

4. СЦЕНАРИИ

A. Поддержка
Вход: текст обращения клиента.
Выход: категория, резюме, приоритет, следующее действие, извлечённые поля.

B. Продажи
Вход: текст лида или заявки.
Выход: категория hot/warm/cold/spam, score 0-100, следующий шаг, поля.

C. Документы
Вход: текст ТЗ, брифа или договора.
Выход: извлечённые поля и черновик КП по шаблону, без выдуманных цен.

D. CallPilot: QA звонков
Вход: транскрипт звонка.
Выход: карточка, QA-чек-лист из 10 критериев, auto_pass или manual_review.
Адресное приложение для колл-центров находится в папке call-center.
Запуск: call-center\start.bat, интерфейс: http://127.0.0.1:8020

5. ТРЕБОВАНИЯ

• Python 3.10 или новее, проверено на Python 3.12.10.
• Windows, Linux или macOS.
• Ключ AITUNNEL и баланс для live-прогона.
• SQLite входит в стандартную библиотеку Python.

6. УСТАНОВКА

Шаг 1. Создать виртуальное окружение.

python -m venv .venv

Шаг 2. Установить зависимости.

Windows PowerShell:
.venv\Scripts\python.exe -m pip install -r requirements.txt

Linux или macOS:
.venv/bin/python -m pip install -r requirements.txt

Полный набор зафиксированных версий находится в requirements.lock.txt.

Шаг 3. Создать локальный файл .env.

Windows PowerShell:
Copy-Item .env.example .env

Linux или macOS:
cp .env.example .env

7. НАСТРОЙКА .ENV

Файл .env создаётся как копия .env.example и не коммитится в Git.

AITUNNEL_API_KEY=sk-your-key-here
AITUNNEL_BASE_URL=https://api.aitunnel.ru/v1/
AITUNNEL_MODEL=gpt-4o-mini
AITUNNEL_TEMPERATURE=0.2
AITUNNEL_MAX_TOKENS=2500
AITUNNEL_TIMEOUT=60
DATABASE_PATH=data/app.db
LOG_LEVEL=INFO
DEBUG=false

Вставьте реальный ключ вместо sk-your-key-here. Модель можно заменить без
изменения кода: gpt-4.1-mini даёт более сильное следование инструкциям,
deepseek-v4-flash дешевле. В текущей локальной конфигурации используется
deepseek/deepseek-v4.1-flash-1017; значение по умолчанию в .env.example —
gpt-4o-mini.

Проверить ключ и модель:

.venv\Scripts\python.exe -m scripts.smoke_llm

8. ЗАПУСК API

Быстрый запуск на Windows: дважды щёлкните start.bat или выполните в консоли:

start.bat

Скрипт останавливает старый uvicorn на порту 8030, очищает кэш Python,
создаёт .venv при необходимости, ставит зависимости, создаёт .env из
.env.example, если файла нет, и запускает новый сервер.
База данных и результаты не удаляются.

Ручной запуск, Windows PowerShell:
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8030 --reload

Linux или macOS:
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8030 --reload

После запуска откройте:

http://127.0.0.1:8030/docs
http://127.0.0.1:8030/health

9. API

POST /ingest — обработка входа.
GET /scenarios — список сценариев и схем.
GET /results — список результатов, фильтры scenario, status, limit, offset.
GET /results/{request_id} — результат по ID.
GET /audit/{request_id} — журнал обработки, сырой ответ при include_raw=true.
GET /stats — статистика.
GET /health — статус приложения, БД и LLM-конфига.
GET /export/results.csv — экспорт результатов.
GET /export/audit.jsonl — экспорт журнала.

Пример запроса через PowerShell:

Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8030/ingest -ContentType "application/json" -Body '{"scenario":"support","text":"Оплатил заказ №12345, доставки нет. Анна, +7 900 123-45-67."}'

Пример запроса через curl:

curl -X POST http://127.0.0.1:8030/ingest -H "Content-Type: application/json" -d "{\"scenario\":\"support\",\"text\":\"Оплатил заказ №12345, доставки нет. Анна, +7 900 123-45-67.\"}"

Ответ содержит request_id, scenario, status, result, meta и error.
HTTP 200 означает, что запрос обработан; итог смотрите в поле status.
HTTP 422 возвращается только при неверном теле запроса.

10. КОНТРОЛЬ КАЧЕСТВА

Правила применяются после Pydantic-валидации:

• confidence=low — принудительная эскалация.
• Нет критичных полей — принудительная эскалация.
• Модель сама поставила escalate=true — решение уважается.
• Score не совпадает с категорией лида — эскалация.
• Пустые summary или next_action — эскалация.
• Невалидный JSON — статус invalid и fallback-результат.
• Ответ обрезан по max_tokens — повтор с удвоенным лимитом; если снова обрезан — error.
• Ошибка LLM или API — статус error и fallback-результат.
• Чистый спам в продажах отклоняется без эскалации.

Статусы: processed, escalated, invalid, error.
При любом статусе клиент получает бизнес-результат. Для invalid и error
это fallback с действием Передать оператору для ручной обработки.

11. ЖУРНАЛ И ДЕЙСТВИЕ

Таблица processing_log хранит вход, хеш входа, сырой ответ LLM, результат,
статус, ошибку, модель, температуру, latency, usage и metadata.

Таблица business_results хранит бизнес-результат: категорию, приоритет,
резюме, следующее действие, поля, confidence и признак эскалации.

Действие на выходе: запись в business_results и экспорт CSV/JSONL.
Сырой ответ LLM доступен через /audit/{request_id} при include_raw=true
или при DEBUG=true.

12. ТЕСТЫ

Все тесты используют fake LLM и не тратят деньги:

.venv\Scripts\python.exe -m pytest -q

Проверяются схемы, контроль качества, эскалация, API, база, экспорт и формат
README. Сейчас в наборе 75 тестов, все проходят. Live-прогон запускается
отдельно через CLI и требует реального ключа AITUNNEL.

13. ТЕСТОВЫЕ ВХОДЫ

Файл data/test_cases.jsonl содержит 30 кейсов: по 10 на каждый сценарий.
Среди них есть явные кейсы, нехватка данных, спам, длинная жалоба и попытки
prompt injection.

Пакетный прогон с реальным LLM:

.venv\Scripts\python.exe -m app.cli batch --strict

Результаты сохраняются в data/test_run.json и data/test_run.csv.
Тестовая база: data/test_run.db.

Сводка по прогону в docs/test_run_summary.md:

.venv\Scripts\python.exe -m scripts.summarize_run

14. РЕЗУЛЬТАТЫ

Live-прогон на AITUNNEL выполнен на модели deepseek/deepseek-v4.1-flash-1017.
Результат: 30 валидных бизнес-результатов, 0 invalid и 0 error,
20 обработано автоматически, 10 эскалировано, 66.7 процента автоматизации.
Средняя задержка 3397 мс, стоимость 2.04 рубля. Подробная сводка:
docs/test_run_summary.md.

15. ПРОВЕРКА README

README намеренно написан без markdown-разметки. Проверка:

.venv\Scripts\python.exe -m scripts.check_readme

Скрипт ищет заголовки, жирный текст, код, ссылки, таблицы и списки markdown.
После каждого изменения проекта README проверяется заново.

16. ОГРАНИЧЕНИЯ

• Один вход и одно действие на выходе: API и SQLite.
• Нет авторизации и мультитенантности.
• Нет интеграций с CRM и почтой.
• SQLite подходит для MVP, но не для высокой конкурентной нагрузки.
• Вход и результат хранятся локально; для реальных персональных данных нужны
  маскирование, шифрование, срок хранения и соблюдение 152-ФЗ.
• Модель может ошибаться; поэтому есть валидация, эскалация и аудит.

17. ПЛАН V2

• PostgreSQL и очередь задач для горизонтального масштабирования.
• JSON Schema в response_format для моделей, которые её поддерживают.
• Repair-попытка при невалидном JSON перед эскалацией.
• Маскирование персональных данных до отправки в LLM.
• Интеграции с CRM и почтой.
• Веб-интерфейс для оператора.
• A/B-сравнение моделей и промптов на одном наборе кейсов.

18. ДОКУМЕНТАЦИЯ

docs/TZ.md — техническое задание по шаблону.
docs/REPORT.md — отчёт по практике.
docs/DEFENSE.md — сценарий защиты на 5-7 минут.
docs/DEMO.md — сценарий демо на 2-3 минуты.
docs/ACCEPTANCE.md — чек-лист приёмки.
docs/test_run_summary.md — результаты live-прогона.
docs/economics.txt — мини-экономика.
docs/feedback_templates.txt — шаблоны откликов.
docs/feedback_log.csv — трекер 60 откликов.
docs/portfolio.txt — упаковка кейса в портфолио.
docs/architecture.mmd — схема архитектуры.
docs/reference/Тех Задание_Шаблон .txt — исходный шаблон технического задания.
start.bat — быстрый запуск на Windows.
scripts/stop_server.ps1 — остановка старого uvicorn перед запуском.
call-center/README.md — приложение CallPilot для колл-центров.
call-center/DESIGN_SYSTEM.md — дизайн-система и настройки CallPilot.
call-center/OFFER.md — адресное коммерческое предложение.
call-center/OUTREACH.md — шаблоны точечной рассылки.
call-center/screenshots/ — скриншоты CallPilot.

19. АВТОР И СРОКИ

Учебный проект, день 8 из 14, 14-20 ноября 2026.
Репозиторий: https://github.com/markmus11012020-max/Project-by-Lida
