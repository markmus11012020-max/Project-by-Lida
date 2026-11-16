# Call-Pilot — служебный runbook

**Для AI-агента: прочитай этот файл первым, если пользователь спрашивает про сайт, сервер, деплой, домен, почту или доступы.**

## 1. Что это за проект

- Бренд: **Call-Pilot** — всегда через дефис. Не `CallPilot`.
- Продукт: AI-постобработка звонков, HITL-карточка в CRM и QA-контроль.
- Основной сайт: https://call-pilot.ru
- Демо: https://call-pilot.ru/dashboard
- Оффер: https://call-pilot.ru/offer
- Группа: Aillix, контакт: `aillix@mail.ru`, ИНН 631306493907.
- Репозиторий: https://github.com/markmus11012020-max/Project-by-Lida
- Локальная папка: `D:\PROJECT`
- Ветка: `main`.

## 2. Что развёрнуто на сервере

| Параметр | Значение |
|---|---|
| Провайдер | REG.RU Cloud |
| Сервер | Amethyst Erbium, ID 8354241 |
| IP | `89.104.70.185` |
| Регион | Санкт-Петербург |
| ОС | Ubuntu 26.04 LTS |
| Ресурсы | 2 vCPU, 2 ГБ RAM, 40 ГБ NVMe |
| Приложение | `/opt/callpilot` |
| Пользователь сервиса | `callpilot` |
| Python | `/opt/callpilot/.venv/bin/python` |
| Порт приложения | `127.0.0.1:8030` |
| Nginx | `80/443`, проксирует на 8030 |
| systemd | `callpilot.service` |
| Nginx config | `/etc/nginx/sites-available/callpilot` |
| `.env` | `/opt/callpilot/.env`, не в Git |
| База | SQLite `/opt/callpilot/call-center/data/call_center.db` |
| Демо-видео | `/opt/callpilot/call-center/demo/callpilot-demo.mp4` |
| Текущий commit | `0452d49` |

На сервере запущен **только CallPilot**. Основной generic API `app.main` на сервере не запущен. PostgreSQL, worker и scheduler на сервере не запущены.

## 3. SSH

Вход только по ключу, пароль не нужен:

```bash
ssh -i ~/.ssh/id_ed25519 root@89.104.70.185
```

Ключ: `C:\Users\Honor\.ssh\id_ed25519`, публичный ключ добавлен в `/root/.ssh/authorized_keys`.

Не запрашивать пароль. Не выводить содержимое `.env` в чат. Не коммитить `.env`.

## 4. Домены и DNS

| Домен | Назначение |
|---|---|
| `call-pilot.ru` | основной сайт |
| `www.call-pilot.ru` | 301 на `call-pilot.ru` |
| `call-pilot.online` | 301 на `call-pilot.ru` |
| `www.call-pilot.online` | 301 на `call-pilot.ru` |

A-записи указывают на `89.104.70.185`.

HTTPS: Let's Encrypt, сертификаты до **14.02.2027**, автопродление Certbot включено.

## 5. Демо-режим

На сервере:

```text
DEMO_MODE=true
```

Это значит:

- форма загрузки аудио скрыта;
- `POST /review/upload` → 403;
- `POST /calls/{id}/process` → 403;
- «Пересчитать» не показывается;
- реальные звонки на публичном сервере не принимаются;
- работают только 6 синтетических звонков, QA, HITL и подтверждение.

**Не выключать `DEMO_MODE` без явного согласования.** Иначе публичные посетители смогут загружать реальные ПДн и тратить LLM-бюджет.

## 6. Почта

SMTP:

```text
smtp.mail.ru:465
username: aillix@mail.ru
from: aillix@mail.ru
to: aillix@mail.ru
SSL: true
```

Пароль приложения Mail.ru хранится только в `/opt/callpilot/.env` как `SMTP_PASSWORD`. В Git и в чат не попадает.

Заявки:

- сохраняются в таблицу `leads`;
- отправляются на `aillix@mail.ru` в фоне;
- если SMTP недоступен, заявка всё равно сохраняется.

Проверка количества заявок:

```bash
ssh -i ~/.ssh/id_ed25519 root@89.104.70.185 \
  "/opt/callpilot/.venv/bin/python - <<'PY'
import sqlite3
c=sqlite3.connect('/opt/callpilot/call-center/data/call_center.db')
print(c.execute('select count(*) from leads').fetchone()[0])
for row in c.execute('select id,name,contact,created_at from leads order by created_at desc limit 10'):
    print(row)
PY"
```

## 7. Деплой

Локально:

```bash
cd D:\PROJECT
git add ...
git commit -m "..."
git push
```

На сервере:

```bash
ssh -i ~/.ssh/id_ed25519 root@89.104.70.185
cd /opt/callpilot
git fetch origin
git reset --hard origin/main
.venv/bin/python -m pip install -r requirements.txt
systemctl restart callpilot
```

Проверка:

```bash
systemctl is-active callpilot
curl -fsS https://call-pilot.ru/health
```

Если менялись только шаблоны/CSS/статика, `pip install` можно пропустить, но `systemctl restart callpilot` всё равно нужен.

## 8. Локальный запуск

CallPilot:

```text
call-center\start.bat
http://127.0.0.1:8020/
```

Основной API:

```text
start.bat
http://127.0.0.1:8030/docs
```

Проверки:

```bash
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m scripts.check_readme
```

Актуально: 168 тестов проходят, 4 пропущены (Postgres-интеграции без внешней БД).

## 9. Что где лежит

| Что | Путь |
|---|---|
| Лендинг | `call-center/templates/landing.html` |
| Оффер | `call-center/templates/offer.html` |
| Dashboard | `call-center/templates/dashboard.html` |
| Карточка звонка | `call-center/templates/call_detail.html` |
| CSS | `call-center/static/style.css` |
| Скриншоты | `call-center/screenshots/` |
| Демо-аудио | `call-center/static/audio/` |
| Демо-видео | `call-center/demo/callpilot-demo.mp4`, не в Git |
| Миграции | `migrations/versions/` |
| Задание Aillix | `docs/AILLIX_CALLPILOT_CARD.md` |
| План V2 | `docs/V2_PLAN.md`, не в Git |

## 10. Полезные команды на сервере

```bash
systemctl status callpilot --no-pager
journalctl -u callpilot -n 100 --no-pager
nginx -t
systemctl reload nginx
certbot renew --dry-run
df -h
free -m
```

## 11. Ограничения текущего контура

- Нет автоматического бэкапа БД: включить резервное копирование REG.RU или cron-бэкап.
- Нет worker/scheduler/Postgres на сервере: это демо-контур.
- Реальные звонки не принимаются.
- `AUDIO_ENCRYPTION_KEY` не задан; для демо используется development-ключ. Для реальных записей задать ключ.
- Нет rate limit на форму заявки; при спаме добавить Nginx limit_req или captcha.
- Нет мониторинга uptime, кроме systemd.

## 12. Если что-то сломалось

### Сайт не открывается

```bash
systemctl status nginx callpilot
nginx -t
curl -I http://127.0.0.1:8030/health
```

### 502 Bad Gateway

Приложение не слушает 8030:

```bash
journalctl -u callpilot -n 100 --no-pager
systemctl restart callpilot
```

### Письма не приходят

- проверить `MAIL_ENABLED=true`;
- проверить `SMTP_PASSWORD` в `.env`;
- проверить `journalctl -u callpilot` на ошибку SMTP;
- проверить «Спам» в Mail.ru.

### Забыт пароль SSH

Пароль не нужен. Использовать ключ `~/.ssh/id_ed25519`. Если ключ потерян — восстановить доступ через консоль REG.RU и добавить новый публичный ключ.

## 13. Правила для следующих AI-сессий

1. Сначала читать этот файл.
2. Не искать домен и сервер заново.
3. Не выводить `.env`, SMTP-пароль, AITUNNEL-ключ и приватные ключи.
4. Не выключать `DEMO_MODE` без разрешения.
5. Не запускать worker/scheduler на этом сервере без отдельного решения.
6. Перед деплоем проверять `git status`, тесты и README.
7. После деплоя проверять `/health` и главную страницу.
8. Для Aillix использовать `docs/AILLIX_CALLPILOT_CARD.md`.
