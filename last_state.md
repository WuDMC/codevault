 📋 Текущее Состояние Проекта

  Проект: CodeVault (форк EchoVault) - Multi-user remote memory server
  Репозиторий: github.com/WuDMC/codevault

  ✅ Что Сделано (Локально)

  1. PostgreSQL 18.2 — обновлено с pg16 на pg18
  2. Переименование — echovault → codevault (все файлы)
  3. Dockerfile — добавлен libsqlite3-dev
  4. docker-compose.yml — исправлен volume mount для PostgreSQL 18
  5. Makefile — создан для удобного управления
  6. CLAUDE.md — инструкции по деплою
  7. Локальное тестирование — успешно:
    - PostgreSQL 18.2 работает
    - Таблицы создаются автоматически
    - Пользователь test_local создан (token: 18b647...)
    - MCP server на порту 8420

  ⏳ Следующий Шаг: Деплой на VM

  VM: instance-wu-2 (GCP, europe-west1-b)
  IP: 34.38.211.154
  Состояние VM:
  - ✅ PostgreSQL 12 остановлен
  - ✅ Docker установлен
  - ✅ Репо склонировано в /opt/memory-server

  Команды для деплоя:
  # Через Makefile:
  make deploy-vm

  # Или вручную:
  gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette

  Готов продолжить с деплоем?
