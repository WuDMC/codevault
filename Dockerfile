FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libsqlite3-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e .

# Create memory home directory
RUN mkdir -p /app/.memory

# Expose SSE port
EXPOSE 8420

# Default command (can be overridden in docker-compose.yml)
CMD ["memory", "mcp", "--transport", "sse", "--port", "8420", "--host", "0.0.0.0"]
