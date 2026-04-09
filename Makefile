.PHONY: help build up down restart logs logs-postgres logs-mcp ps clean test user-add user-list db-shell deploy-vm

# Default target
help:
	@echo "CodeVault - Makefile Commands"
	@echo ""
	@echo "Local Development:"
	@echo "  make setup       - Copy .env.example to .env (first time setup)"
	@echo "  make build       - Build Docker images"
	@echo "  make up          - Start all services (PostgreSQL + Memory MCP + pgAdmin)"
	@echo "  make down        - Stop all services"
	@echo "  make restart     - Restart all services"
	@echo "  make ps          - Show running containers"
	@echo "  make logs        - Show all logs"
	@echo "  make logs-postgres - Show PostgreSQL logs"
	@echo "  make logs-mcp    - Show Memory MCP server logs"
	@echo "  make clean       - Stop services and remove volumes (DANGER: deletes data!)"
	@echo ""
	@echo "Database:"
	@echo "  make db-shell    - Open PostgreSQL shell"
	@echo "  make db-version  - Show PostgreSQL version"
	@echo "  make db-tables   - List all tables"
	@echo "  make db-backup   - Backup database to backup-YYYYMMDD.sql"
	@echo "  make db-restore FILE=backup.sql - Restore database from file"
	@echo ""
	@echo "User Management:"
	@echo "  make user-add NAME=username - Create new user"
	@echo "  make user-list   - List all users"
	@echo ""
	@echo "Testing:"
	@echo "  make test        - Run tests locally"
	@echo "  make test-conn   - Test SSE connection"
	@echo ""
	@echo "Deployment:"
	@echo "  make deploy-vm   - Deploy to GCP VM (instance-wu-2)"
	@echo "  make vm-logs     - Show VM logs"
	@echo "  make vm-status   - Show VM status"

# Setup
setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ .env created from .env.example"; \
		echo "⚠️  Edit .env and add your POSTGRES_PASSWORD and OPENAI_API_KEY"; \
	else \
		echo "⚠️  .env already exists"; \
	fi

# Docker Compose commands
build:
	docker-compose build

up:
	docker-compose up -d
	@echo "✅ Services started"
	@echo "PostgreSQL: localhost:5432"
	@echo "Memory MCP: localhost:8420"
	@echo "pgAdmin: http://localhost:5050"

down:
	docker-compose down

restart:
	docker-compose restart

ps:
	docker-compose ps

logs:
	docker-compose logs -f

logs-postgres:
	docker-compose logs -f postgres

logs-mcp:
	docker-compose logs -f memory-mcp

clean:
	@echo "⚠️  WARNING: This will delete all data in PostgreSQL!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		docker-compose down -v; \
		echo "✅ All services stopped and volumes removed"; \
	else \
		echo "❌ Cancelled"; \
	fi

# Database commands
db-shell:
	docker exec -it memory-postgres psql -U postgres memory

db-version:
	docker exec memory-postgres psql -U postgres -c "SELECT version();"

db-tables:
	docker exec memory-postgres psql -U postgres memory -c "\dt"

db-backup:
	@mkdir -p backups
	docker exec memory-postgres pg_dump -U postgres memory > backups/backup-$$(date +%Y%m%d-%H%M%S).sql
	@echo "✅ Backup saved to backups/backup-$$(date +%Y%m%d-%H%M%S).sql"

db-restore:
	@if [ -z "$(FILE)" ]; then \
		echo "❌ Error: FILE parameter required"; \
		echo "Usage: make db-restore FILE=backup.sql"; \
		exit 1; \
	fi
	cat $(FILE) | docker exec -i memory-postgres psql -U postgres memory
	@echo "✅ Database restored from $(FILE)"

# User management
user-add:
	@if [ -z "$(NAME)" ]; then \
		echo "❌ Error: NAME parameter required"; \
		echo "Usage: make user-add NAME=username"; \
		exit 1; \
	fi
	@docker exec memory-mcp-server bash -c '\
		if [ ! -f /app/.memory/config.yaml ]; then \
			mkdir -p /app/.memory && \
			cat > /app/.memory/config.yaml << EOF\n\
storage:\n\
  backend: postgresql\n\
  url: postgresql://postgres:$${POSTGRES_PASSWORD:-changeme}@postgres:5432/memory\n\
\n\
embedding:\n\
  provider: openai\n\
  model: text-embedding-3-small\n\
  api_key: $${OPENAI_API_KEY}\n\
EOF\n\
		fi && \
		memory user add $(NAME)'

user-list:
	docker exec memory-postgres psql -U postgres memory -c "SELECT id, name, created_at FROM users ORDER BY id;"

# Testing
test:
	docker-compose up -d
	@sleep 5
	@echo "Testing PostgreSQL connection..."
	docker exec memory-postgres psql -U postgres -c "SELECT version();"
	@echo "Testing Memory MCP server..."
	curl -s http://localhost:8420/sse | head -5 || echo "MCP server not responding"

test-conn:
	@echo "Testing SSE connection to Memory MCP server..."
	curl -v http://localhost:8420/sse

# VM Deployment
deploy-vm:
	@echo "🚀 Deploying to GCP VM (instance-wu-2)..."
	@echo ""
	@echo "Step 1: Updating repository on VM..."
	gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette --command "\
		cd /opt/memory-server && \
		sudo git pull origin main && \
		echo '✅ Repository updated'"
	@echo ""
	@echo "Step 2: Setting up .env file..."
	@echo "⚠️  You need to manually create .env on the VM with:"
	@echo "    gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette"
	@echo "    cd /opt/memory-server"
	@echo "    sudo nano .env"
	@echo ""
	@echo "Step 3: Rebuilding and starting services..."
	gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette --command "\
		cd /opt/memory-server && \
		sudo docker compose up -d --build && \
		sleep 5 && \
		sudo docker compose ps"
	@echo ""
	@echo "✅ Deployment complete! Check logs with: make vm-logs"

vm-logs:
	gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette --command "\
		cd /opt/memory-server && sudo docker compose logs -f"

vm-status:
	gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette --command "\
		cd /opt/memory-server && sudo docker compose ps"

# Git shortcuts
git-status:
	git status

git-push:
	git add -A
	git commit -m "$(MSG)"
	git push origin main

# Development
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
