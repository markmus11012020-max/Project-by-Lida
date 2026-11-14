"""Synthetic demo calls for CallPilot.

All names, phones and order numbers are fictional. Audio is generated
separately by scripts/build_demo_audio.py.
"""

from __future__ import annotations

from typing import Any

DEMO_CALLS: list[dict[str, Any]] = [
    {
        "id": "call_01",
        "title": "Задержка доставки",
        "client": "Анна",
        "operator": "Дмитрий",
        "operator_voice": "ru-RU-DmitryNeural",
        "client_voice": "ru-RU-SvetlanaNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Здравствуйте, компания Ромашка, меня зовут Дмитрий. Чем могу помочь?",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Здравствуйте, я оплатила заказ номер 12345 три дня назад, но доставки до сих пор нет.",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Понимаю вас, давайте проверю статус заказа. Одну минуту, пожалуйста.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Хорошо, буду ждать.",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Заказ действительно задержался на складе. Доставка запланирована на завтра до 18:00. Я отправил уведомление курьеру.",
            },
            {
                "id": "s6",
                "speaker": "Клиент",
                "text": "Спасибо, буду ждать.",
            },
            {
                "id": "s7",
                "speaker": "Оператор",
                "text": "Всего доброго. Если будут вопросы, звоните, мы на связи.",
            },
        ],
    },
    {
        "id": "call_02",
        "title": "Возврат денег",
        "client": "Мария",
        "operator": "Анна",
        "operator_voice": "ru-RU-SvetlanaNeural",
        "client_voice": "ru-RU-DmitryNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Здравствуйте, компания Ромашка, Анна слушает.",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Здравствуйте, мне пришёл бракованный товар. Хочу вернуть деньги сегодня.",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Да, конечно, я гарантирую, что деньги вернутся сегодня. Никаких проблем.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Точно сегодня? Мне нужно оплатить лечение.",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Да, я обещаю. Ждите смс.",
            },
            {
                "id": "s6",
                "speaker": "Клиент",
                "text": "Хорошо, надеюсь.",
            },
            {
                "id": "s7",
                "speaker": "Оператор",
                "text": "До свидания.",
            },
        ],
    },
    {
        "id": "call_03",
        "title": "Техническая ошибка",
        "client": "Ольга",
        "operator": "Дмитрий",
        "operator_voice": "ru-RU-DmitryNeural",
        "client_voice": "ru-RU-SvetlanaNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Здравствуйте, компания Ромашка.",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Здравствуйте, не могу войти в личный кабинет, пишет ошибку 403.",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Попробуйте очистить кэш браузера и войти снова. Если не поможет, напишите на support@romashka.ru.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Поняла, попробую.",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Хорошо.",
            },
        ],
    },
    {
        "id": "call_04",
        "title": "Жалоба на оператора",
        "client": "Сергей",
        "operator": "Анна",
        "operator_voice": "ru-RU-SvetlanaNeural",
        "client_voice": "ru-RU-DmitryNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Здравствуйте, компания Ромашка, меня зовут Анна.",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Здравствуйте, вчера ваш оператор нагрубил мне и бросил трубку. Я хочу жалобу.",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Понимаю вас. Это не моя смена, но я могу передать жалобу руководителю.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Передайте, пожалуйста. Ещё я не получила заказ номер 555.",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Заказ номер 555 доставят завтра. Жалобу передам, с вами свяжутся.",
            },
            {
                "id": "s6",
                "speaker": "Клиент",
                "text": "Хорошо.",
            },
            {
                "id": "s7",
                "speaker": "Оператор",
                "text": "До свидания.",
            },
        ],
    },
    {
        "id": "call_05",
        "title": "Смена адреса доставки",
        "client": "Елена",
        "operator": "Анна",
        "operator_voice": "ru-RU-SvetlanaNeural",
        "client_voice": "ru-RU-DmitryNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Здравствуйте, компания Ромашка, меня зовут Анна. Чем могу помочь?",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Здравствуйте, хочу изменить адрес доставки по заказу номер 777.",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Уточните, пожалуйста, новый адрес.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Москва, улица Ленина, дом 10, квартира 5.",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Адрес обновил. Заказ доставят по новому адресу в течение двух дней.",
            },
            {
                "id": "s6",
                "speaker": "Клиент",
                "text": "Спасибо.",
            },
            {
                "id": "s7",
                "speaker": "Оператор",
                "text": "Пожалуйста. Всего доброго.",
            },
        ],
    },
    {
        "id": "call_06",
        "title": "Плохая связь",
        "client": "Неизвестен",
        "operator": "Дмитрий",
        "operator_voice": "ru-RU-DmitryNeural",
        "client_voice": "ru-RU-SvetlanaNeural",
        "segments": [
            {
                "id": "s1",
                "speaker": "Оператор",
                "text": "Алло?",
            },
            {
                "id": "s2",
                "speaker": "Клиент",
                "text": "Алло, это доставка? Я заказ... связь плохая...",
            },
            {
                "id": "s3",
                "speaker": "Оператор",
                "text": "Я вас плохо слышу. Повторите, пожалуйста.",
            },
            {
                "id": "s4",
                "speaker": "Клиент",
                "text": "Заказ не пришёл, уже неделя. Алло?",
            },
            {
                "id": "s5",
                "speaker": "Оператор",
                "text": "Какой номер заказа? Я не понял.",
            },
            {
                "id": "s6",
                "speaker": "Клиент",
                "text": "Не помню... связь прерывается...",
            },
            {
                "id": "s7",
                "speaker": "Оператор",
                "text": "Алло? Вас не слышно.",
            },
        ],
    },
]


def transcript_text(call: dict[str, Any]) -> str:
    return "\n".join(
        f"[{segment['id']}] {segment['speaker']}: {segment['text']}"
        for segment in call["segments"]
    )


def demo_call(call_id: str) -> dict[str, Any] | None:
    return next((call for call in DEMO_CALLS if call["id"] == call_id), None)
