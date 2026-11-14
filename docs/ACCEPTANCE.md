# Чек-лист приёмки

## Статус на текущий момент

- Mock-тесты: 75 passed.
- README без markdown: проверка проходит.
- Live-прогон: выполнен, 30/30 валидных, 0 invalid и 0 error.
- Автоматизация: 20 кейсов, 10 эскалаций, 66.7 процента.
- Мини-экономика: рассчитана, экономия 66.7 процента.
- Демо и защита: сценарии готовы, записи выполняются отдельно.
- 60 откликов: шаблоны и трекер готовы, отправка выполняется отдельно.

## Маппинг критериев задания

| Критерий задания | Где доказательство | Статус |
|---|---|---|
| Процесс работает на 10 тестовых входах | data/test_cases.jsonl, 30 кейсов, tests/test_cases_mock.py | live 30/30, mock 68 passed |
| LLM выдаёт структурированный JSON | app/scenarios, app/schemas.py | готово |
| JSON валидируется, есть эскалация | app/qc.py, tests/test_qc.py | готово |
| Журнал обработки: вход, выход, статус | app/db.py, processing_log, GET /audit/{id} | готово |
| Действие на выходе: БД или файл | business_results, GET /export/results.csv | готово |
| System prompt задаёт правила | app/scenarios/support.py, sales.py, documents.py | готово |
| Temperature выбрана осознанно | .env.example, README, температура 0.2 | готово |
| README воспроизводит результат | README.md, scripts/check_readme.py | готово |
| Демо 2-3 минуты | docs/DEMO.md | сценарий готов |
| Защита 5-7 минут | docs/DEFENSE.md | сценарий готов |
| Отчёт по практике | docs/REPORT.md | черновик готов |
| Мини-экономика | scripts/economics.py, docs/economics.txt | рассчитана, экономия 66.7 процента |
| 60 откликов | docs/feedback_templates.txt, docs/feedback_log.csv | шаблоны и трекер готовы |
| CallPilot для колл-центров | call-center/, screenshot, OFFER.md, OUTREACH.md | демо, 6 звонков, QA-чек-лист, оффер готовы |

## Команды финальной проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.check_readme
.venv\Scripts\python.exe -m app.cli batch --strict
.venv\Scripts\python.exe -m scripts.summarize_run
.venv\Scripts\python.exe -m scripts.economics
```

## Что проверить перед сдачей

- [x] Реальный ключ AITUNNEL вставлен в .env.
- [x] Live-прогон 30 кейсов прошёл без invalid и error.
- [x] Число эскалаций и автоматизации совпадает с ожиданием или объяснено.
- [x] docs/test_run_summary.md заполнен реальными цифрами.
- [x] docs/REPORT.md обновлён реальными цифрами.
- [x] docs/economics.txt сгенерирован.
- [x] README проверен после последних изменений.
- [x] В Git нет .env, базы и ключей.
- [x] CallPilot собран, скриншоты и оффер готовы.
- [ ] Демо-видео записано.
- [ ] Защита записана.
- [ ] 60 откликов отправлены и отмечены в трекере.
