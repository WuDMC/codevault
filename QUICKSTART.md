# Quick Start: Remote Multi-User Memory in 15 Minutes

This guide gets you from **zero to working remote memory** for you and your wife in ~15 minutes.

---

## Prerequisites

- GCP VM (e2-micro is fine, ~$7/month)
- SSH access to VM
- 2 laptops (yours + wife's)
- OpenAI API key (for embeddings)

---

## Choose Your Setup Method

**Option A: Docker (Recommended)** — 3 минуты, все автоматически
**Option B: Manual** — 5 минут, больше контроля

---

## Option A: Docker Setup (Faster!)

### Step 1: Server Setup with Docker (3 minutes)

SSH into your GCP VM:

```bash
# Install Docker
sudo apt-get update
sudo apt-get install -y docker.io docker-compose git
sudo systemctl start docker
sudo systemctl enable docker

# Clone this fork
cd /opt
sudo git clone https://github.com/YOUR_USERNAME/echovault.git memory-server
cd memory-server

# Setup environment
cp .env.example .env
nano .env
# Set:
# POSTGRES_PASSWORD=your_strong_password
# OPENAI_API_KEY=sk-your_key

# Start services (PostgreSQL + Memory MCP)
sudo docker-compose up -d

# Wait 10 seconds for PostgreSQL to initialize
sleep 10

# Create users
sudo docker exec memory-mcp-server memory user add sasha
# Save the token!

sudo docker exec memory-mcp-server memory user add wife
# Save the token!

# Done! Memory server running on port 8420
curl http://localhost:8420/sse
```

**Jump to Step 2 (Client Setup)**

---

## Option B: Manual Setup (More Control)

### Step 1: Server Setup (5 minutes)

SSH into your GCP VM:

```bash
# Install PostgreSQL 16 + pgvector
sudo apt-get update
sudo apt-get install -y postgresql-16 postgresql-16-pgvector python3-pip git

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database
sudo -u postgres createdb memory
sudo -u postgres psql -d memory -c "CREATE EXTENSION vector;"
sudo -u postgres psql -d memory -c "CREATE EXTENSION pgcrypto;"
sudo -u postgres psql -c "ALTER USER postgres PASSWORD 'CHANGE_ME_STRONG_PASSWORD';"

# Clone and install this fork
cd /opt
sudo git clone https://github.com/YOUR_USERNAME/echovault.git memory-server
cd memory-server
sudo pip install -e .

# Create config
mkdir -p ~/.memory
cat > ~/.memory/config.yaml << 'EOF'
storage:
  backend: postgresql
  url: postgresql://postgres:CHANGE_ME_STRONG_PASSWORD@localhost:5432/memory

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-YOUR_OPENAI_KEY_HERE
EOF

# Initialize database (creates tables)
memory init

# Create users
memory user add sasha
# Save the token shown!

memory user add wife
# Save the token shown!

# Start MCP server
nohup memory mcp --transport sse --port 8420 --host 0.0.0.0 > /tmp/memory-mcp.log 2>&1 &

# Check it's running
curl http://localhost:8420/sse
# Should respond with SSE connection attempt
```

---

## Step 2: Client Setup - Your Laptop (5 minutes)

On your laptop:

```bash
# Install this fork
pip install git+https://github.com/YOUR_USERNAME/echovault.git

# Create config
mkdir -p ~/.memory
cat > ~/.memory/config.yaml << 'EOF'
storage:
  backend: postgresql
  url: postgresql://postgres:CHANGE_ME_STRONG_PASSWORD@YOUR_VM_IP:5432/memory

auth:
  token: PASTE_YOUR_TOKEN_FROM_STEP1_HERE

embedding:
  provider: openai
  model: text-embedding-3-small
  api_key: sk-YOUR_OPENAI_KEY_HERE
EOF

# Configure Claude Code
mkdir -p ~/.claude
cat > ~/.claude/settings.json << 'EOF'
{
  "mcpServers": {
    "memory": {
      "type": "sse",
      "url": "http://YOUR_VM_IP:8420/sse",
      "headers": {
        "Authorization": "Bearer PASTE_YOUR_TOKEN_HERE"
      }
    }
  }
}
EOF

# Test connection
memory search "test"
# Should connect to remote server and return empty results (no memories yet)
```

---

## Step 3: Client Setup - Wife's Laptop (5 minutes)

Same as Step 2, but use **wife's token** instead of yours.

---

## Step 4: Test It! (5 minutes)

### On Your Laptop

Open Claude Code and chat:

```
You: Can you save a memory about our authentication system?

Claude: [calls memory_save with details about auth system]

You: Now search for "authentication"

Claude: [calls memory_search, finds the memory you just saved]
```

### On Wife's Laptop

Open Claude Code and chat:

```
Wife: Search for "authentication"

Claude: [returns empty — she can't see your memories! User isolation works!]

Wife: Save a memory about CSS styling

Claude: [saves successfully, scoped to wife's user_id]
```

### Verify Isolation

On your laptop:
```
You: Search for "CSS styling"

Claude: [returns empty — you can't see wife's memories!]
```

✅ **User isolation confirmed!**

---

## Troubleshooting

### Server Not Responding?

```bash
# Check server logs
tail -f /tmp/memory-mcp.log

# Check PostgreSQL is running
sudo systemctl status postgresql

# Test PostgreSQL connection
psql postgresql://postgres:PASSWORD@localhost:5432/memory -c "SELECT COUNT(*) FROM users;"
```

### Client Connection Failed?

```bash
# Test SSE endpoint
curl -H "Authorization: Bearer YOUR_TOKEN" http://VM_IP:8420/sse

# Check firewall
sudo ufw status
sudo ufw allow 8420/tcp  # if needed
```

### Token Invalid?

```bash
# On server, list users and their tokens
ssh YOUR_VM
memory user list
# Copy the correct token to your client config
```

---

## What's Next?

### Production Hardening

1. **SSL/HTTPS** — Use Nginx + Let's Encrypt (see `SETUP_MULTIUSER.md`)
2. **Systemd service** — Run MCP server as daemon (see `SETUP_MULTIUSER.md`)
3. **Firewall** — Only expose port 443 (HTTPS), not 8420 directly
4. **Backups** — `pg_dump memory > backup.sql` (automate with cron)

### Optional: Ollama for Free Embeddings

```yaml
# On server config.yaml, switch to Ollama
embedding:
  provider: ollama
  model: nomic-embed-text
  base_url: http://localhost:11434

# Install Ollama on VM
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text
```

---

## Cost Breakdown

- **GCP e2-micro**: $6-8/month
- **Storage (10GB HDD)**: $0.20/month
- **OpenAI embeddings**: ~$0.01/1000 memories (negligible)
- **Total**: ~$7-9/month for unlimited memories for 2 users

Compare to:
- Claude Pro: $40/month/user × 2 = $80/month
- **You're saving $70/month!**

---

## Summary

You now have:

✅ Remote memory server running on GCP
✅ PostgreSQL with pgvector for semantic search
✅ Multi-user support (you + wife, isolated data)
✅ SSE transport for remote access
✅ Token-based auth
✅ Claude Code integration

**Total time:** ~15 minutes
**Total cost:** ~$7/month

Enjoy your persistent memory! 🧠
