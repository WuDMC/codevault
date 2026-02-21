# Docker Setup: PostgreSQL как Отдельный Сервис

## Быстрый Старт

```bash
# 1. Клонируй репозиторий
git clone https://github.com/YOUR_USERNAME/codevault.git
cd codevault

# 2. Настрой environment variables
cp .env.example .env
nano .env
# Установи:
#   POSTGRES_PASSWORD=your_strong_password
#   OPENAI_API_KEY=sk-your_openai_key

# 3. Запусти все сервисы
docker-compose up -d

# 4. Создай пользователей
docker exec memory-mcp-server memory user add sasha
docker exec memory-mcp-server memory user add wife

# 5. Готово! Проверь:
curl http://localhost:8420/sse  # Memory MCP server
psql postgresql://postgres:password@localhost:5432/memory  # PostgreSQL
open http://localhost:5050  # pgAdmin (Web UI)
```

---

## Структура Docker Compose

```yaml
services:
  postgres:        # PostgreSQL 16 + pgvector (port 5432)
  memory-mcp:      # Memory MCP server (port 8420)
  pgadmin:         # pgAdmin Web UI (port 5050)
```

### PostgreSQL (отдельный сервис!)

- **Port**: `5432` (exposed — другие приложения могут подключаться)
- **Image**: `pgvector/pgvector:pg16`
- **Data**: `postgres-data` volume (персистентное хранилище)
- **Health check**: автоматическая проверка готовности

**Другие приложения могут подключаться:**
```python
import psycopg2
conn = psycopg2.connect("postgresql://postgres:password@localhost:5432/memory")
```

### Memory MCP Server

- **Port**: `8420` (SSE transport)
- **Depends on**: `postgres`
- **Environment**: `POSTGRES_URL`, `OPENAI_API_KEY`
- **Command**: `memory mcp --transport sse --port 8420 --host 0.0.0.0`

**Можно останавливать независимо:**
```bash
docker-compose stop memory-mcp   # PostgreSQL продолжит работать
```

### pgAdmin (опционально)

- **Port**: `5050`
- **Login**: `admin@example.com` / `admin` (или из `.env`)
- **Web UI**: http://localhost:5050

---

## Управление Сервисами

```bash
# Запустить все
docker-compose up -d

# Запустить только PostgreSQL (без memory server)
docker-compose up -d postgres

# Запустить PostgreSQL + pgAdmin (без memory server)
docker-compose up -d postgres pgadmin

# Остановить memory server (PostgreSQL продолжит работу)
docker-compose stop memory-mcp

# Перезапустить PostgreSQL
docker-compose restart postgres

# Логи
docker-compose logs -f postgres      # PostgreSQL логи
docker-compose logs -f memory-mcp    # Memory MCP логи

# Остановить все
docker-compose down

# Удалить данные (ОСТОРОЖНО!)
docker-compose down -v
```

---

## Подключение к PostgreSQL

### Из Контейнера

```bash
docker exec -it memory-postgres psql -U postgres memory

# SQL:
\dt                          # список таблиц
SELECT COUNT(*) FROM users;  # проверка
```

### Из Хоста

```bash
psql postgresql://postgres:PASSWORD@localhost:5432/memory
```

### Из Другого Docker Контейнера

```yaml
# docker-compose.yml вашего приложения
services:
  my-app:
    image: my-app:latest
    environment:
      DATABASE_URL: postgresql://postgres:password@postgres:5432/memory
    networks:
      - memory-network

networks:
  memory-network:
    external: true
```

### Из Python/Node.js/etc (на хосте)

```python
import psycopg2
conn = psycopg2.connect(
    host="localhost",  # или Docker IP
    port=5432,
    database="memory",
    user="postgres",
    password="your_password"
)
```

---

## Использование PostgreSQL для Других Приложений

### Вариант 1: Другая Схема

```sql
docker exec -it memory-postgres psql -U postgres memory

-- Создай свою схему
CREATE SCHEMA my_app;

-- Создай таблицы в своей схеме
CREATE TABLE my_app.logs (id SERIAL, message TEXT);

-- Memory server использует public.memories
-- Твое приложение использует my_app.logs
-- Никакой конфликт!
```

### Вариант 2: Другая База Данных

```sql
docker exec -it memory-postgres psql -U postgres

-- Создай новую БД
CREATE DATABASE my_other_app;

-- Подключись к ней
\c my_other_app

-- Теперь у тебя 2 БД на одном PostgreSQL:
-- - memory (для memory server)
-- - my_other_app (для другого приложения)
```

---

## Бэкапы и Восстановление

### Backup

```bash
# Полный дамп БД
docker exec memory-postgres pg_dump -U postgres memory > backup-$(date +%Y%m%d).sql

# Автоматический бэкап (cron)
0 2 * * * docker exec memory-postgres pg_dump -U postgres memory > /backups/memory-$(date +\%Y\%m\%d).sql
```

### Restore

```bash
# Восстановить из дампа
cat backup.sql | docker exec -i memory-postgres psql -U postgres memory
```

---

## Мониторинг

### pgAdmin (Web UI)

```bash
# Уже запущен в docker-compose
open http://localhost:5050

# Login: admin@example.com / admin
# Add server:
#   Host: postgres
#   Port: 5432
#   User: postgres
#   Password: (from .env)
```

### CLI Мониторинг

```bash
docker exec memory-postgres psql -U postgres memory

-- Размеры таблиц
SELECT
    tablename,
    pg_size_pretty(pg_total_relation_size('public.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public';

-- Активные подключения
SELECT count(*) FROM pg_stat_activity;

-- Индексы
\di
```

---

## Production Deployment

### Добавь Nginx Reverse Proxy

```yaml
# docker-compose.yml — добавь nginx сервис
nginx:
  image: nginx:alpine
  ports:
    - "443:443"
    - "80:80"
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf
    - /etc/letsencrypt:/etc/letsencrypt
  depends_on:
    - memory-mcp
```

### SSL с Let's Encrypt

```bash
# Установи certbot на хосте
sudo apt-get install certbot

# Получи сертификат
sudo certbot certonly --standalone -d memory.yourdomain.com

# Сертификаты в /etc/letsencrypt/live/memory.yourdomain.com/
```

---

## Troubleshooting

### PostgreSQL не запускается

```bash
# Проверь логи
docker-compose logs postgres

# Проверь, что порт 5432 свободен
sudo netstat -tlnp | grep 5432

# Пересоздай контейнер
docker-compose down
docker-compose up -d postgres
```

### Memory MCP не подключается к PostgreSQL

```bash
# Проверь health check PostgreSQL
docker-compose ps

# Должно быть: postgres (healthy)

# Проверь логи
docker-compose logs memory-mcp

# Проверь connection string в .env
cat .env | grep POSTGRES_URL
```

### Потерян пароль PostgreSQL

```bash
# Посмотри в .env
cat .env | grep POSTGRES_PASSWORD

# Или подключись без пароля (из контейнера)
docker exec -it memory-postgres psql -U postgres
```

---

## Очистка и Сброс

### Удалить все данные

```bash
# Остановить и удалить контейнеры + volumes
docker-compose down -v

# Это удалит:
# - Все таблицы PostgreSQL
# - Всех пользователей
# - Все memories
# - pgAdmin настройки
```

### Пересоздать только память (сохранить PostgreSQL)

```bash
# Удалить только memory-mcp контейнер
docker-compose stop memory-mcp
docker-compose rm -f memory-mcp

# Пересоздать
docker-compose up -d memory-mcp
```

---

## Резюме

✅ **PostgreSQL — отдельный Docker контейнер** (независимый сервис)
✅ **Memory MCP — отдельный Docker контейнер** (клиент PostgreSQL)
✅ **pgAdmin — опциональный Web UI** для управления PostgreSQL
✅ **Другие приложения могут подключаться** к PostgreSQL на порту 5432
✅ **Легко бэкапить, мониторить, масштабировать**

---

## Что Дальше?

1. **Запусти**: `docker-compose up -d`
2. **Создай пользователей**: `docker exec memory-mcp-server memory user add <name>`
3. **Подключи клиентов** (ноутбуки) — см. [QUICKSTART.md](./QUICKSTART.md)
4. **Добавь другое приложение** к тому же PostgreSQL — см. [POSTGRES_AS_SERVICE.md](./POSTGRES_AS_SERVICE.md)
5. **Production**: SSL, Nginx, автоматические бэкапы

🎉 **Docker setup complete!**
