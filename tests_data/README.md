# Тестовые данные Call-Pilot

Файл `inputs.jsonl` — 10 кейсов для сквозного прогона через JSON API.

## Формат

```json
{
  "id": "case_01",
  "title": "Задержка доставки",
  "client": "Анна",
  "operator": "Дмитрий",
  "transcript": "Оператор: ...\nКлиент: ...",
  "expected_need_review": null,
  "expected_reason": "informational"
}
```

Поле `expected_need_review`:

- `true` — кейс обязан уйти в ручную проверку;
- `null` — информационный кейс, фактическое решение зависит от модели.

В наборе пять asserted-кейсов с `need_review=true`:

- `case_02` — ложное обещание возврата (critical);
- `case_04` — двойное списание;
- `case_05` — консультация по возврату;
- `case_07` — угроза судом и Роспотребнадзором (critical);
- `case_08` — отмена заказа с возвратом.

Остальные 5 кейсов показывают auto-pass: доставка, вход в кабинет,
благодарность, смена адреса, ошиблись номером.

## Запуск

Приложение должно быть запущено на `http://127.0.0.1:8020`:

```powershell
.venv\Scripts\python.exe call-center\scripts\run_tests_data.py --strict
```

Скрипт создаёт звонки через `POST /api/v1/calls`, запускает
`POST /api/v1/calls/{id}/process`, сравнивает asserted-кейсы
и пишет `last_run.json`.

`--strict` завершается с ошибкой, только если не совпал asserted-кейс.
Информационные кейсы не ломают прогон.
