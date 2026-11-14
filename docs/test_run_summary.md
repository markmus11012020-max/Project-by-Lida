# Результаты live-прогона

Модель: deepseek/deepseek-v4.1-flash-1017
Всего кейсов: 30
Валидный бизнес-результат: 30
Обработано автоматически: 20
Эскалировано: 10
Невалидный JSON: 0
Ошибок LLM/API: 0
Совпадение с ожидаемым статусом: 30/30
Средняя задержка: 3397 мс
Суммарная стоимость: 2.0400 ₽
Уровень автоматизации: 66.7%

## Разбивка по сценариям

| Сценарий | Кейсов | processed | escalated | invalid | error |
|---|---|---|---|---|---|
| support | 10 | 6 | 4 | 0 | 0 |
| sales | 10 | 7 | 3 | 0 | 0 |
| documents | 10 | 7 | 3 | 0 | 0 |

## Кейсы

| Кейс | Ожидание | Факт | OK | Confidence | Причина |
|---|---|---|---|---|---|
| support_01 | processed | processed | да | high | - |
| support_02 | processed | processed | да | high | - |
| support_03 | processed | processed | да | high | - |
| support_04 | processed | processed | да | high | - |
| support_05 | escalated | escalated | да | high | жалоба на курьера требует проверки человеком |
| support_06 | processed | processed | да | high | - |
| support_07 | escalated | escalated | да | medium | missing_contact; missing_critical_fields |
| support_08 | escalated | escalated | да | low | insufficient_data; low_confidence; missing_critical_fields |
| support_09 | escalated | escalated | да | low | prompt_injection_suspected; low_confidence |
| support_10 | - | processed | да | high | - |
| sales_01 | processed | processed | да | high | - |
| sales_02 | processed | processed | да | medium | - |
| sales_03 | processed | processed | да | medium | - |
| sales_04 | processed | processed | да | high | - |
| sales_05 | processed | processed | да | high | - |
| sales_06 | processed | processed | да | high | - |
| sales_07 | escalated | escalated | да | low | insufficient_data; low_confidence; missing_critical_fields |
| sales_08 | escalated | escalated | да | low | insufficient_data; low_confidence; missing_critical_fields |
| sales_09 | escalated | escalated | да | low | prompt_injection_suspected; low_confidence |
| sales_10 | processed | processed | да | high | - |
| documents_01 | processed | processed | да | high | - |
| documents_02 | processed | processed | да | high | - |
| documents_03 | processed | processed | да | high | - |
| documents_04 | processed | processed | да | high | - |
| documents_05 | processed | processed | да | high | - |
| documents_06 | processed | processed | да | high | - |
| documents_07 | escalated | escalated | да | low | insufficient_data; low_confidence; missing_critical_fields |
| documents_08 | escalated | escalated | да | low | insufficient_data; low_confidence; missing_critical_fields |
| documents_09 | escalated | escalated | да | low | prompt_injection_suspected; low_confidence |
| documents_10 | processed | processed | да | high | - |

## Выводы

Все кейсы дали валидный бизнес-результат и совпали с ожидаемым статусом. Промпты и правила эскалации работают стабильно.
