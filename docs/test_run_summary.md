# Результаты тестового прогона Call-Pilot

Всего кейсов: 10
Asserted: 5, совпало: 5
Информационных: 5
need_review ожидалось: 5, получено: 5

| ID | Кейс | QA | auto_qa_status | need_review | asserted | результат |
|---|---|---:|---|---|---|---|
| case_01 | Задержка доставки | 100 | auto_pass | нет | — | OK |
| case_02 | Возврат: ложное обещание | 0 | manual_review | да | да | OK |
| case_03 | Ошибка входа 403 | 95 | auto_pass | нет | — | OK |
| case_04 | Двойное списание | 85 | manual_review | да | да | OK |
| case_05 | Консультация по возврату | 95 | manual_review | да | да | OK |
| case_06 | Положительный отзыв | 95 | auto_pass | нет | — | OK |
| case_07 | Угроза судом | 75 | manual_review | да | да | OK |
| case_08 | Отмена заказа | 95 | manual_review | да | да | OK |
| case_09 | Изменение адреса | 95 | auto_pass | нет | — | OK |
| case_10 | Ошиблись номером | 100 | auto_pass | нет | — | OK |

Asserted-кейсы — это 5 сценариев, где ручная проверка обязательна:
2 critical (ложное обещание возврата, угроза судом) и 3 возврата/списания.
Остальные 5 кейсов информационные: модель может пройти их автоматически.

Команда: `.venv\Scripts\python.exe call-center\scripts\run_tests_data.py --strict`
