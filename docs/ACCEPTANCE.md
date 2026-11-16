# Чек-лист приёмки выпускного проекта

## Статус

- Автотесты: 187 passed, 4 skipped.
- README: проверка plain-text проходит.
- Тестовый прогон: 10 кейсов, 5 asserted с `need_review=true`,
  включая 2 critical; 5/5 asserted совпало.
- Демо-видео: 2:25.
- Защита: 6:34.
- Секреты: `.env` не в Git, в репозитории только `.env.example`.

## Маппинг требований

| Требование | Где доказательство | Статус |
|---|---|---|
| Ссылка на репозиторий | https://github.com/markmus11012020-max/Project-by-Lida | готово |
| README: запуск, окружение, 3 curl | `README.md` | готово |
| `.env.example` без секретов | `.env.example` | готово |
| Dockerfile | `Dockerfile` | готово |
| 10 тестовых входов | `tests_data/inputs.jsonl` | готово |
| 2+ кейса с ручной проверкой | 5 asserted с `need_review=true`, 5/5 совпало | готово |
| Демо-видео 2–4 минуты | `call-center/demo/callpilot-demo.mp4` | готово |
| Защита 5–7 минут | `call-center/demo/callpilot-defense.mp4`, `docs/DEFENSE.md` | готово |
| Отчёт по шаблону | `docs/REPORT.md` | готово |
| API: создание | `POST /api/v1/calls` | готово |
| API: чтение | `GET /api/v1/calls` | готово |
| API: AI-обработка | `POST /api/v1/calls/{id}/process` | готово |
| БД: 2–4 таблицы | `demo_calls`, `call_reviews`, `audit_runs`, `leads` | готово |
| `audit_runs` с полями | `action`, `input_json`, `output_json`, `status`, `error`, `duration_ms`, `created_at` | готово |
| `need_review=true` + причина | `call_reviews.need_review`, `review_reason`, API и UI | готово |
| Веб-панель: список | `/dashboard` | готово |
| Веб-панель: карточка | `/calls/{id}` | готово |
| Веб-панель: аудит | `/audit` | готово |
| Мини-экономика | `docs/economics.txt`, ROI на лендинге | готово |
| Экспорт CSV/JSONL | `/export/results.csv`, `/export/audit.jsonl` | готово |
| Скриншоты ключевых действий | `call-center/screenshots/` | готово |

## Команды финальной проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.check_readme
.venv\Scripts\python.exe call-center\scripts\run_tests_data.py --strict
```

## Что проверить перед сдачей

- [x] Репозиторий приватный, доступ у проверяющего есть.
- [x] `.env` и ключи не в Git.
- [x] README запускает проект за 10 минут.
- [x] API создаёт звонок и возвращает `call_id`.
- [x] AI-обработка возвращает строгий JSON.
- [x] `need_review=true` и `review_reason` видны в API и UI.
- [x] `audit_runs` заполняется.
- [x] Экспорт CSV и JSONL работает.
- [x] 10 тестовых кейсов проходят.
- [x] Демо-видео записано.
- [x] Защита записана.
- [x] Отчёт заполнен.
- [ ] Проверить ссылку на видео у проверяющего.
- [ ] Проверить доступ к приватному репозиторию.
