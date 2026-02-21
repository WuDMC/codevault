# CodeVault - Multi-User Remote Memory Server

## Project Overview

CodeVault (forked from EchoVault) is a **multi-user remote memory system** for coding agents with PostgreSQL + pgvector backend.

### Key Features
- PostgreSQL 18.2 + pgvector for remote storage
- Multi-user support with token-based authentication
- SSE/HTTP transport for remote MCP access
- Docker Compose setup for easy deployment
- Backward compatible with SQLite (local mode)

---

## Quick Start (Local Testing)

```bash
# Clone repository
git clone https://github.com/WuDMC/codevault.git
cd codevault

# Setup environment
cp .env.example .env
nano .env  # Add POSTGRES_PASSWORD and OPENAI_API_KEY

# Start services
docker-compose up -d

# Verify PostgreSQL 18.2
docker exec memory-postgres psql -U postgres -c "SELECT version();"

# Create test user
docker exec memory-mcp-server bash -c "cat > /app/.memory/config.yaml << 'EOF'
storage:
  backend: postgresql
  url: postgresql://postgres:YOUR_PASSWORD@postgres:5432/memory
embedding:
  provider: openai
  model: text-embedding-3-small
EOF"

docker exec memory-mcp-server memory user add test_user

# Stop services
docker-compose down
```

---

## Deployment to GCP VM (instance-wu-2)

### Current Infrastructure
- **VM**: instance-wu-2 (e2-micro, europe-west1-b)
- **IP**: 34.38.211.154
- **Domain**: wudmc.com (Astro SSR site)
- **Nginx**: Configured with SSL (Let's Encrypt)

### Pre-Deployment Checklist
✅ Old PostgreSQL 12 stopped and disabled
✅ Docker installed
✅ Port 5432 free
✅ Repository cloned to `/opt/memory-server`

### Deployment Steps

```bash
# 1. SSH into VM
gcloud compute ssh instance-wu-2 --zone europe-west1-b --project geo-roulette

# 2. Update repository
cd /opt/memory-server
sudo git pull origin main

# 3. Setup environment
sudo cp .env.example .env
sudo nano .env
# Set:
# POSTGRES_PASSWORD=STRONG_PASSWORD_HERE
# OPENAI_API_KEY=sk-YOUR_KEY_HERE

# 4. Start services
sudo docker-compose up -d

# 5. Wait for PostgreSQL to initialize
sleep 10
sudo docker-compose ps  # All should be "Up" and "healthy"

# 6. Create config for MCP server
sudo docker exec memory-mcp-server bash -c "cat > /app/.memory/config.yaml << 'EOF'
storage:
  backend: postgresql
  url: postgresql://postgres:YOUR_PASSWORD@postgres:5432/memory

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-YOUR_KEY
EOF"

# 7. Create users
sudo docker exec memory-mcp-server memory user add sasha
# Save the token!

sudo docker exec memory-mcp-server memory user add wife
# Save the token!

# 8. Verify
sudo docker exec memory-postgres psql -U postgres memory -c "SELECT * FROM users;"
curl http://localhost:8420/sse  # Should connect via SSE

# 9. (Optional) Setup Nginx reverse proxy for memory.wudmc.com
sudo nano /etc/nginx/sites-available/memory
# See SETUP_MULTIUSER.md for Nginx config

# 10. Check logs
sudo docker-compose logs -f memory-mcp
```

---

## Nginx Configuration (Optional)

To expose Memory MCP server via `memory.wudmc.com`:

```nginx
# /etc/nginx/sites-available/memory
server {
    server_name memory.wudmc.com;

    location /sse {
        proxy_pass http://localhost:8420;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_buffering off;
        proxy_cache off;
    }

    listen 80;
}

# Enable site
sudo ln -s /etc/nginx/sites-available/memory /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Add SSL with Let's Encrypt
sudo certbot --nginx -d memory.wudmc.com
```

---

## Client Setup (Laptops)

### Option 1: Direct IP Access

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://34.38.211.154:8420/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### Option 2: Domain with SSL (Recommended)

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "https://memory.wudmc.com/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

---

## Troubleshooting

### Container not starting
```bash
# Check logs
sudo docker-compose logs postgres
sudo docker-compose logs memory-mcp

# Restart services
sudo docker-compose restart
```

### Port already in use
```bash
# Check what's using port
sudo netstat -tlnp | grep -E "5432|8420"

# Stop old PostgreSQL if needed
sudo systemctl stop postgresql
sudo systemctl disable postgresql
```

### Database connection issues
```bash
# Test PostgreSQL connection
sudo docker exec memory-postgres psql -U postgres memory -c "SELECT version();"

# Check tables
sudo docker exec memory-postgres psql -U postgres memory -c "\dt"
```

---

## Maintenance

### Backup Database
```bash
# Backup
sudo docker exec memory-postgres pg_dump -U postgres memory > backup-$(date +%Y%m%d).sql

# Restore
cat backup.sql | sudo docker exec -i memory-postgres psql -U postgres memory
```

### View Logs
```bash
sudo docker-compose logs -f memory-mcp
sudo docker-compose logs -f postgres
```

### Update Code
```bash
cd /opt/memory-server
sudo git pull origin main
sudo docker-compose down
sudo docker-compose up -d --build
```

---

## Architecture

```
Laptop (You)                          GCP VM (instance-wu-2)
┌─────────────────┐                  ┌──────────────────────┐
│ Claude Code     │                  │ memory mcp (SSE)     │
│   ↕ MCP SSE     │─── HTTPS ────→  │   port 8420          │
│ token=abc123    │                  │   ↕                  │
└─────────────────┘                  │ PostgreSQL 18.2      │
                                     │   + pgvector         │
Laptop (Wife)                        │   user_id scoping    │
┌─────────────────┐                  │                      │
│ Claude Code     │                  │ Nginx (optional SSL) │
│   ↕ MCP SSE     │─── HTTPS ────→  │   memory.wudmc.com   │
│ token=xyz789    │                  │                      │
└─────────────────┘                  └──────────────────────┘
```

---

## Security Notes

- Never commit `.env` file (already in `.gitignore`)
- Use strong PostgreSQL password (min 20 chars)
- Tokens are 64-char random hex strings (256 bits entropy)
- User isolation at database level (`WHERE user_id = X`)
- Use SSL in production (Nginx + Let's Encrypt)
- Firewall: only expose 80, 443 publicly (8420 via Nginx only)

---

## Cost Estimate

- **VM**: e2-micro → $6-8/month
- **Storage**: 10GB HDD → $0.20/month
- **OpenAI embeddings**: ~$0.01/1000 memories → negligible
- **Total**: ~$7-9/month for 2 users

---

## Next Steps

1. ✅ Local testing complete
2. ⏳ Deploy to VM
3. ⏳ Create users (sasha, wife)
4. ⏳ Test from both laptops
5. ⏳ Setup Nginx + SSL (optional)
6. ⏳ Configure automated backups

---

## References

- [QUICKSTART.md](./QUICKSTART.md) - 15-minute setup guide
- [SETUP_MULTIUSER.md](./SETUP_MULTIUSER.md) - Complete setup instructions
- [DOCKER_README.md](./DOCKER_README.md) - Docker management
- [POSTGRES_AS_SERVICE.md](./POSTGRES_AS_SERVICE.md) - PostgreSQL as independent service
- [IMPLEMENTATION_SUMMARY.md](./IMPLEMENTATION_SUMMARY.md) - Technical details

---

**Status**: Ready for deployment 🚀
