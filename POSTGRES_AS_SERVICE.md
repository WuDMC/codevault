# PostgreSQL как Отдельный Сервис

PostgreSQL в этой архитектуре — **полностью независимый сервис**, который может использоваться не только memory server'ом, но и **любыми другими приложениями**.

---

## Архитектура: Раздельные Сервисы

```
┌────────────────────────────────────────────────┐
│                  GCP VM / Docker               │
│                                                │
│  ┌─────────────────────────────────────────┐  │
│  │  PostgreSQL 16 + pgvector               │  │
│  │  port: 5432 (exposed)                   │  │
│  │  ✅ Отдельный процесс/контейнер         │  │
│  │  ✅ Может использоваться другими apps   │  │
│  └─────────────────────────────────────────┘  │
│              ↕                                 │
│  ┌─────────────────────────────────────────┐  │
│  │  Memory MCP Server                      │  │
│  │  port: 8420 (SSE)                       │  │
│  │  ✅ Отдельный процесс/контейнер         │  │
│  │  ✅ Подключается к PostgreSQL как клиент│  │
│  └─────────────────────────────────────────┘  │
│              ↕                                 │
│  ┌─────────────────────────────────────────┐  │
│  │  Другое приложение (например, FastAPI) │  │
│  │  ✅ Тоже подключается к PostgreSQL      │  │
│  │  ✅ Может использовать те же таблицы    │  │
│  │     или создать свои схемы              │  │
│  └─────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

---

## Вариант 1: Docker Compose (Рекомендуется)

### Шаг 1: Подготовка

```bash
cd echovault-fork

# Скопируй пример env файла
cp .env.example .env

# Отредактируй .env
nano .env
# Установи:
# POSTGRES_PASSWORD=your_strong_password
# OPENAI_API_KEY=sk-...
```

### Шаг 2: Запуск сервисов

```bash
# Запустить ВСЕ сервисы (PostgreSQL + Memory MCP + pgAdmin)
docker-compose up -d

# Или запустить ТОЛЬКО PostgreSQL (без memory server)
docker-compose up -d postgres

# Или запустить PostgreSQL + pgAdmin (без memory server)
docker-compose up -d postgres pgadmin
```

### Шаг 3: Подключение других приложений

PostgreSQL теперь доступен на `localhost:5432` для **любых приложений**:

```python
# Пример: другое Python приложение
import psycopg2

conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="memory",
    user="postgres",
    password="your_strong_password"
)

# Используй memory таблицы (если нужно)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM memories")
print(cursor.fetchone())

# Или создай свои таблицы
cursor.execute("""
    CREATE TABLE IF NOT EXISTS my_app_data (
        id SERIAL PRIMARY KEY,
        name TEXT
    )
""")
conn.commit()
```

```bash
# Пример: подключение через psql CLI
psql postgresql://postgres:your_strong_password@localhost:5432/memory

# Список таблиц
\dt

# Таблицы memory server:
# - users
# - memories
# - memory_details
# - meta
# - sessions

# Твои таблицы:
CREATE TABLE my_app_logs (id SERIAL, message TEXT);
```

### Шаг 4: Управление через pgAdmin (Web UI)

Открой браузер: `http://localhost:5050`

- Email: `admin@example.com`
- Password: (из `.env` — `PGADMIN_PASSWORD`)

Добавь соединение:
- Host: `postgres` (внутри Docker сети) или `localhost` (снаружи)
- Port: `5432`
- User: `postgres`
- Password: (из `.env` — `POSTGRES_PASSWORD`)

Теперь ты можешь:
- Просматривать таблицы memory server
- Создавать свои таблицы для других приложений
- Выполнять SQL запросы
- Экспортировать данные

---

## Вариант 2: Нативная Установка (без Docker)

### PostgreSQL как Systemd Service

```bash
# Установка PostgreSQL (уже сделано в SETUP_MULTIUSER.md)
sudo systemctl status postgresql

# PostgreSQL — это ОТДЕЛЬНЫЙ сервис
# Memory MCP server — это ОТДЕЛЬНЫЙ сервис

# Они независимы:
sudo systemctl stop memory-mcp      # Memory server остановлен
sudo systemctl status postgresql     # PostgreSQL все еще работает!

# Другие приложения могут подключаться
psql postgresql://postgres:password@localhost:5432/memory
```

---

## Использование PostgreSQL для Других Приложений

### Вариант 1: Разные Схемы (Schemas)

```sql
-- Memory server использует public схему
-- Создай свою схему для другого приложения

CREATE SCHEMA my_fastapi_app;

-- Создай таблицы в своей схеме
CREATE TABLE my_fastapi_app.users (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE
);

-- Memory server не трогает эту схему
-- Твое приложение не трогает public.memories
```

### Вариант 2: Разные Базы Данных

```sql
-- Memory server использует БД "memory"
-- Создай свою БД

CREATE DATABASE my_other_app;

-- Теперь у тебя 2 независимые БД на одном PostgreSQL:
-- - memory (для memory server)
-- - my_other_app (для другого приложения)
```

### Вариант 3: Разные Пользователи

```sql
-- Memory server использует пользователя "postgres"
-- Создай отдельного пользователя для другого приложения

CREATE USER my_app_user WITH PASSWORD 'password';
GRANT CONNECT ON DATABASE memory TO my_app_user;

-- Дай доступ только к определенным таблицам
GRANT SELECT ON memories TO my_app_user;  -- только чтение
-- Или:
GRANT ALL PRIVILEGES ON SCHEMA my_fastapi_app TO my_app_user;
```

---

## Примеры Интеграции

### FastAPI приложение + Memory PostgreSQL

```python
# main.py
from fastapi import FastAPI
import psycopg2

app = FastAPI()

# Подключаемся к ТОЙ ЖЕ PostgreSQL, что и memory server
conn = psycopg2.connect(
    "postgresql://postgres:password@localhost:5432/memory"
)

@app.get("/api/memories")
def get_memories():
    """API endpoint для чтения memories из БД"""
    cursor = conn.cursor()
    cursor.execute("SELECT title, what, created_at FROM memories LIMIT 10")
    rows = cursor.fetchall()
    return {"memories": rows}

@app.post("/api/my-app-data")
def save_my_data(data: dict):
    """API endpoint для сохранения своих данных"""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO my_app_data (name) VALUES (%s)",
        (data["name"],)
    )
    conn.commit()
    return {"status": "ok"}
```

### Jupyter Notebook + Memory PostgreSQL

```python
import psycopg2
import pandas as pd

# Подключаемся к memory PostgreSQL
conn = psycopg2.connect(
    "postgresql://postgres:password@localhost:5432/memory"
)

# Анализируем данные memory server
df = pd.read_sql("""
    SELECT
        user_id,
        category,
        COUNT(*) as count
    FROM memories
    GROUP BY user_id, category
    ORDER BY count DESC
""", conn)

print(df)

# Визуализация
import matplotlib.pyplot as plt
df.plot(kind='bar', x='category', y='count')
plt.show()
```

### Scheduled Backups

```bash
# cron job для бэкапов PostgreSQL
# Работает НЕЗАВИСИМО от memory server!

# crontab -e
0 2 * * * pg_dump memory > /backups/memory-$(date +\%Y\%m\%d).sql
```

---

## Мониторинг PostgreSQL

### Использование pgAdmin (Docker Compose)

```bash
# Уже запущен в docker-compose.yml
# Открой: http://localhost:5050
```

### CLI Мониторинг

```bash
# Подключаемся к PostgreSQL
psql postgresql://postgres:password@localhost:5432/memory

-- Список всех таблиц
\dt

-- Размеры таблиц
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;

-- Активные подключения
SELECT datname, count(*) FROM pg_stat_activity GROUP BY datname;

-- Запросы в данный момент
SELECT pid, usename, application_name, client_addr, state, query
FROM pg_stat_activity
WHERE state != 'idle';
```

---

## Резервное Копирование и Восстановление

### Backup (полная БД)

```bash
# Через Docker
docker exec memory-postgres pg_dump -U postgres memory > backup.sql

# Нативная установка
pg_dump memory > backup.sql
```

### Restore

```bash
# Через Docker
cat backup.sql | docker exec -i memory-postgres psql -U postgres memory

# Нативная установка
psql memory < backup.sql
```

### Backup только memory таблиц

```bash
pg_dump memory \
  --table=users \
  --table=memories \
  --table=memory_details \
  --table=meta \
  --table=sessions \
  > memory-only-backup.sql
```

---

## Производительность и Масштабирование

### Настройки для Малого VM (e2-micro)

```sql
-- /etc/postgresql/16/main/postgresql.conf (нативная установка)
-- или в docker-compose.yml (Docker)

shared_buffers = 128MB
effective_cache_size = 256MB
work_mem = 4MB
maintenance_work_mem = 64MB
max_connections = 20
```

### Настройки для Продакшн (2GB+ RAM)

```sql
shared_buffers = 512MB
effective_cache_size = 1GB
work_mem = 16MB
maintenance_work_mem = 256MB
max_connections = 100
```

### Connection Pooling (для множества приложений)

```bash
# Установи PgBouncer
docker run -d \
  --name pgbouncer \
  --network memory-network \
  -p 6432:6432 \
  -e DB_HOST=postgres \
  -e DB_USER=postgres \
  -e DB_PASSWORD=password \
  -e POOL_MODE=transaction \
  -e MAX_CLIENT_CONN=100 \
  -e DEFAULT_POOL_SIZE=20 \
  pgbouncer/pgbouncer

# Теперь приложения подключаются к PgBouncer:
# postgresql://postgres:password@localhost:6432/memory
```

---

## Безопасность

### 1. Ограничение доступа по IP

```bash
# /etc/postgresql/16/main/pg_hba.conf

# Разрешить только локальные подключения
host  memory  postgres  127.0.0.1/32  md5

# Разрешить подключения с определенных IP
host  memory  postgres  YOUR_LAPTOP_IP/32  md5
host  memory  postgres  YOUR_WIFE_LAPTOP_IP/32  md5

# Запретить все остальные
host  all  all  0.0.0.0/0  reject
```

### 2. SSL соединения

```sql
-- Включи SSL в postgresql.conf
ssl = on
ssl_cert_file = '/path/to/server.crt'
ssl_key_file = '/path/to/server.key'

-- Требуй SSL для подключений
ALTER DATABASE memory SET require_ssl = on;
```

### 3. Разделение прав

```sql
-- Memory server — полный доступ
CREATE USER memory_server WITH PASSWORD 'server_password';
GRANT ALL PRIVILEGES ON DATABASE memory TO memory_server;

-- Другое приложение — только чтение
CREATE USER readonly_user WITH PASSWORD 'readonly_password';
GRANT CONNECT ON DATABASE memory TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;

-- Jupyter / Анализ данных — только чтение
CREATE USER analyst WITH PASSWORD 'analyst_password';
GRANT CONNECT ON DATABASE memory TO analyst;
GRANT SELECT ON memories, memory_details TO analyst;
```

---

## Docker Compose: Команды

```bash
# Запустить все сервисы
docker-compose up -d

# Запустить только PostgreSQL
docker-compose up -d postgres

# Остановить memory server (PostgreSQL продолжит работать)
docker-compose stop memory-mcp

# Перезапустить PostgreSQL
docker-compose restart postgres

# Посмотреть логи PostgreSQL
docker-compose logs -f postgres

# Посмотреть логи Memory MCP server
docker-compose logs -f memory-mcp

# Зайти в PostgreSQL контейнер
docker exec -it memory-postgres psql -U postgres memory

# Остановить все
docker-compose down

# Удалить данные (ОСТОРОЖНО!)
docker-compose down -v
```

---

## Миграция PostgreSQL на Отдельный Хост

Если хочешь вынести PostgreSQL на **отдельный сервер** (не на тот же VM, где memory server):

### На PostgreSQL сервере (VM #1)

```bash
# Установи PostgreSQL
sudo apt-get install postgresql-16 postgresql-16-pgvector

# Разреши внешние подключения
# /etc/postgresql/16/main/postgresql.conf
listen_addresses = '*'

# /etc/postgresql/16/main/pg_hba.conf
host  memory  postgres  MEMORY_SERVER_IP/32  md5

# Перезапусти
sudo systemctl restart postgresql

# Firewall
sudo ufw allow from MEMORY_SERVER_IP to any port 5432
```

### На Memory MCP сервере (VM #2)

```yaml
# ~/.memory/config.yaml
storage:
  backend: postgresql
  url: postgresql://postgres:password@POSTGRES_VM_IP:5432/memory
```

Теперь у тебя:
- **VM #1**: PostgreSQL (может обслуживать множество приложений)
- **VM #2**: Memory MCP server (подключается к VM #1)
- **Laptop 1, 2, ...**: Клиенты (подключаются к VM #2 через SSE)

---

## Резюме

✅ **PostgreSQL — это полностью отдельный сервис**
✅ **Может использоваться множеством приложений одновременно**
✅ **Memory MCP server — просто клиент PostgreSQL**
✅ **Запуск/остановка memory server не влияет на PostgreSQL**
✅ **Можно вынести PostgreSQL на отдельный хост**
✅ **Легко управлять через pgAdmin, psql, или другие инструменты**

---

## Что Дальше?

1. **Запусти сервисы**: `docker-compose up -d`
2. **Подключи другое приложение** к PostgreSQL (FastAPI, Django, etc.)
3. **Настрой бэкапы**: автоматические `pg_dump` через cron
4. **Мониторинг**: pgAdmin или Grafana + Prometheus
5. **Масштабируй**: добавь больше memory MCP серверов (все подключаются к одному PostgreSQL)

🎉 **PostgreSQL как независимый сервис — готов!**
