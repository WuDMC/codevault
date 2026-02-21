# Multi-User PostgreSQL Setup Guide

This guide shows how to set up EchoVault fork for **remote multi-user memory** with PostgreSQL backend.

## Architecture Overview

```
Laptop (You)                          GCP VM
┌─────────────────┐                  ┌──────────────────────┐
│ Claude Code     │                  │ memory mcp (SSE)     │
│   ↕ MCP SSE     │─── HTTPS ────→  │   port 8420          │
│ config: token=A │                  │   ↕                  │
└─────────────────┘                  │ PostgreSQL 16        │
                                     │   + pgvector         │
Laptop (Wife)                        │   user_id scoping    │
┌─────────────────┐                  │                      │
│ Claude Code     │                  │ Nginx (optional SSL) │
│   ↕ MCP SSE     │─── HTTPS ────→  │                      │
│ config: token=B │                  │                      │
└─────────────────┘                  └──────────────────────┘
```

---

## Part 1: Server Setup (GCP VM)

### 1.1 Install PostgreSQL 16 + pgvector

```bash
# Update packages
sudo apt-get update

# Install PostgreSQL 16
sudo apt-get install -y postgresql-16 postgresql-16-pgvector

# Start and enable PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

### 1.2 Configure PostgreSQL

```bash
# Set password for postgres user
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'STRONG_PASSWORD_HERE';"

# Create memory database
sudo -u postgres createdb memory

# Enable extensions
sudo -u postgres psql -d memory -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d memory -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"
```

### 1.3 Allow remote connections (if needed for debugging)

```bash
# Edit pg_hba.conf to allow connections from your IP
sudo nano /etc/postgresql/16/main/pg_hba.conf
# Add line:
# host  memory  postgres  YOUR_IP/32  md5

# Edit postgresql.conf to listen on all interfaces (or specific IP)
sudo nano /etc/postgresql/16/main/postgresql.conf
# Set: listen_addresses = 'localhost'  # or '*' for all

# Restart PostgreSQL
sudo systemctl restart postgresql
```

### 1.4 Install EchoVault fork

```bash
# Clone your fork
cd /opt
sudo git clone https://github.com/YOUR_USERNAME/echovault.git memory-server
cd memory-server

# Install with pip
sudo pip install -e .
```

### 1.5 Create config.yaml

```bash
mkdir -p ~/.memory
nano ~/.memory/config.yaml
```

**Content:**
```yaml
storage:
  backend: postgresql
  url: postgresql://postgres:STRONG_PASSWORD_HERE@localhost:5432/memory

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-YOUR_OPENAI_KEY  # Or set via OPENAI_API_KEY env var
```

### 1.6 Initialize database (creates tables)

```bash
# Run memory init to trigger schema creation
memory init

# Or manually run SQL migration (see db_pg.py _create_schema)
```

### 1.7 Create users

```bash
# Create user for yourself
memory user add sasha
# Output: Token: abc123...

# Create user for wife
memory user add wife
# Output: Token: xyz789...

# Save these tokens! You'll need them on laptops.

# List users
memory user list
```

### 1.8 Run MCP server as systemd service

```bash
sudo nano /etc/systemd/system/memory-mcp.service
```

**Content:**
```ini
[Unit]
Description=Memory MCP Server (SSE)
After=postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/memory-server
ExecStart=/usr/local/bin/memory mcp --transport sse --port 8420 --host 0.0.0.0
Environment=MEMORY_HOME=/home/YOUR_USER/.memory
Environment=OPENAI_API_KEY=sk-YOUR_KEY
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Reload systemd, enable and start service
sudo systemctl daemon-reload
sudo systemctl enable memory-mcp
sudo systemctl start memory-mcp

# Check status
sudo systemctl status memory-mcp

# View logs
sudo journalctl -u memory-mcp -f
```

### 1.9 (Optional) Setup Nginx reverse proxy with SSL

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot certonly --nginx -d memory.yourdomain.com

# Configure Nginx
sudo nano /etc/nginx/sites-available/memory
```

**Content:**
```nginx
server {
    listen 443 ssl;
    server_name memory.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/memory.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/memory.yourdomain.com/privkey.pem;

    location /sse {
        proxy_pass http://127.0.0.1:8420;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;  # IMPORTANT for SSE
        proxy_cache off;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/memory /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## Part 2: Client Setup (Laptops)

### 2.1 Install EchoVault fork

```bash
pip install git+https://github.com/YOUR_USERNAME/echovault.git
```

### 2.2 Create config.yaml

```bash
mkdir -p ~/.memory
nano ~/.memory/config.yaml
```

**Content (Laptop 1 - You):**
```yaml
storage:
  backend: postgresql
  url: postgresql://postgres:PASSWORD@VM_IP:5432/memory

auth:
  token: abc123...  # Token from `memory user add sasha`

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-...
```

**Content (Laptop 2 - Wife):**
```yaml
storage:
  backend: postgresql
  url: postgresql://postgres:PASSWORD@VM_IP:5432/memory

auth:
  token: xyz789...  # Token from `memory user add wife`

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-...
```

### 2.3 Configure Claude Code (SSE transport)

Edit `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://VM_IP:8420/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

**If using Nginx with SSL:**
```json
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "https://memory.yourdomain.com/sse",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
```

### 2.4 Test connection

```bash
# Test CLI search
memory search "test" --remote http://VM_IP:8420 --token YOUR_TOKEN

# Or use Claude Code and try:
# "Search my memories for X"
```

---

## Part 3: Usage

### Saving memories (from Claude Code)

Claude will automatically call `memory_save` when you:
- Make decisions
- Fix bugs
- Discover patterns
- Configure infrastructure

### Searching memories

```bash
# CLI
memory search "authentication bug"

# Claude Code (automatic)
# At session start, Claude calls memory_context to load project history
```

### User isolation

- Each user has their own memories
- Token → user_id → scoped queries
- No way to see other user's memories (unless you have their token)

---

## Troubleshooting

### Server logs
```bash
sudo journalctl -u memory-mcp -f
```

### Test PostgreSQL connection
```bash
psql postgresql://postgres:PASSWORD@VM_IP:5432/memory -c "SELECT COUNT(*) FROM memories;"
```

### Test MCP server
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://VM_IP:8420/sse
```

### Firewall rules
```bash
# Allow port 8420 (if not using Nginx)
sudo ufw allow 8420/tcp

# Or allow Nginx
sudo ufw allow 'Nginx Full'
```

---

## Migration: SQLite → PostgreSQL

To migrate existing SQLite memories to PostgreSQL:

1. Export from SQLite:
```bash
# TODO: implement `memory export --format json`
```

2. Import to PostgreSQL:
```bash
# TODO: implement `memory import --format json`
```

---

## Security Notes

- **Never commit tokens to git**
- Use environment variables for API keys
- Use SSL/HTTPS in production (Nginx + Let's Encrypt)
- Firewall: only expose port 443 (HTTPS) publicly
- Token rotation: regenerate tokens periodically
- Database backups: `pg_dump memory > backup.sql`

---

## Performance Tuning (Small VM)

Edit `/etc/postgresql/16/main/postgresql.conf`:

```
shared_buffers = 128MB
effective_cache_size = 256MB
work_mem = 4MB
maintenance_work_mem = 64MB
max_connections = 20
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

---

## Cost Estimate (GCP e2-micro)

- VM: $6-8/month (e2-micro, preemptible)
- Storage: ~$0.20/month (10GB HDD)
- Network: minimal (MCP traffic is small)
- **Total: ~$7-9/month**

For just 2 users, this is very cost-effective!

---

## Next Steps

- [ ] Test save/search from both laptops
- [ ] Verify user isolation
- [ ] Setup automated backups
- [ ] Configure SSL with Let's Encrypt
- [ ] Monitor PostgreSQL performance
