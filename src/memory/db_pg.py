"""PostgreSQL database layer with pgvector for multi-user memory storage."""

import json
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector

from memory.models import Memory, MemoryDetail


def _normalize_row(row: dict) -> dict:
    """Normalize PG row: convert datetime objects to ISO strings."""
    result = dict(row)
    for key in ("created_at", "updated_at", "started_at", "ended_at"):
        val = result.get(key)
        if isinstance(val, datetime):
            result[key] = val.isoformat()
    return result


class MemoryDBPostgres:
    """PostgreSQL database for storing and searching memories (multi-user)."""

    def __init__(self, db_url: str, user_id: Optional[int] = None) -> None:
        """Initialize database connection and create schema.

        Args:
            db_url: PostgreSQL connection URL
            user_id: User ID for scoping queries (required for non-admin operations)
        """
        self.db_url = db_url
        self.user_id = user_id
        self.conn = psycopg2.connect(db_url)
        self.conn.autocommit = False

        # Register pgvector types
        register_vector(self.conn)

        # Create schema if needed (only once per database, not every connection)
        self._ensure_schema()

    def _safe_cursor(self, dict_cursor: bool = False):
        """Get a cursor, rolling back any aborted transaction first.

        Args:
            dict_cursor: If True, return a RealDictCursor for dict-style access

        Returns:
            A psycopg2 cursor
        """
        if self.conn.closed:
            self.conn = psycopg2.connect(self.db_url)
            self.conn.autocommit = False
            register_vector(self.conn)
        # psycopg2 transaction_status: 0=IDLE, 1=IN_TRANSACTION, 4=IN_ERROR
        status = self.conn.info.transaction_status
        if status == 4:
            self.conn.rollback()
        elif status == 1:
            # Commit any idle-in-transaction to keep connection clean
            self.conn.commit()
        if dict_cursor:
            return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self.conn.cursor()

    def _ensure_schema(self) -> None:
        """Create schema only if tables don't exist yet."""
        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'memories'
                )
            """)
            exists = cursor.fetchone()[0]
            self.conn.commit()
            if not exists:
                self._create_schema()
        except Exception:
            self.conn.rollback()
            raise

    def _create_schema(self) -> None:
        """Create database tables and indexes if they don't exist."""
        cursor = self._safe_cursor()

        # Enable extensions (requires superuser on first run)
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          SERIAL PRIMARY KEY,
                name        VARCHAR(100) NOT NULL UNIQUE,
                token       VARCHAR(64) NOT NULL UNIQUE
                            DEFAULT encode(gen_random_bytes(32), 'hex'),
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Memories table (core storage)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id          BIGSERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                memory_id   VARCHAR(36) NOT NULL,
                title       TEXT NOT NULL,
                what        TEXT NOT NULL,
                why         TEXT,
                impact      TEXT,
                tags        TEXT[] DEFAULT '{}',
                category    VARCHAR(50) DEFAULT 'note',
                project     VARCHAR(255),
                source      TEXT,
                agent       TEXT,
                related_files TEXT[] DEFAULT '{}',
                file_path   TEXT NOT NULL,
                section_anchor TEXT,
                embedding   VECTOR(1536),
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_count INTEGER DEFAULT 0,
                UNIQUE(user_id, memory_id)
            )
        """)

        # Memory details table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS memory_details (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                memory_id   VARCHAR(36) NOT NULL,
                body        TEXT NOT NULL,
                PRIMARY KEY (user_id, memory_id),
                FOREIGN KEY (user_id, memory_id) REFERENCES memories(user_id, memory_id) ON DELETE CASCADE
            )
        """)

        # Metadata table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                key         TEXT NOT NULL,
                value       TEXT NOT NULL,
                PRIMARY KEY (user_id, key)
            )
        """)

        # Indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_user
            ON memories (user_id, created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_project
            ON memories (user_id, project, created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories (user_id, category, created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_tags
            ON memories USING GIN (tags)
        """)

        # Vector index (HNSW)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_embedding
            ON memories USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)

        # Full-text search column and index
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='memories' AND column_name='fts'
                ) THEN
                    ALTER TABLE memories ADD COLUMN fts TSVECTOR
                        GENERATED ALWAYS AS (
                            to_tsvector('english',
                                COALESCE(title, '') || ' ' ||
                                COALESCE(what, '') || ' ' ||
                                COALESCE(why, '') || ' ' ||
                                COALESCE(impact, '')
                            )
                        ) STORED;
                END IF;
            END $$;
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_fts
            ON memories USING GIN (fts)
        """)

        # Sessions table (optional)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id          BIGSERIAL PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                project     VARCHAR(255),
                summary     TEXT,
                files_changed TEXT[],
                started_at  TIMESTAMPTZ DEFAULT NOW(),
                ended_at    TIMESTAMPTZ
            )
        """)

        # Migration: add agent column if missing
        cursor.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name='memories' AND column_name='agent'
                ) THEN
                    ALTER TABLE memories ADD COLUMN agent TEXT;
                    CREATE INDEX idx_memories_agent ON memories (user_id, agent);
                END IF;
            END $$;
        """)

        self.conn.commit()

    def has_vec_table(self) -> bool:
        """Check if vector index exists (always True for PG)."""
        return True

    def drop_vec_table(self) -> None:
        """Drop and recreate the vector index."""
        cursor = self._safe_cursor()
        cursor.execute("DROP INDEX IF EXISTS idx_memories_embedding")
        cursor.execute("UPDATE memories SET embedding = NULL WHERE user_id = %s", (self.user_id,))
        self.conn.commit()

    def _create_vec_table(self, dim: int) -> None:
        """Recreate the HNSW vector index after reindex.

        Args:
            dim: Embedding dimension (used for compatibility, PG column is fixed)
        """
        cursor = self._safe_cursor()
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_memories_embedding
            ON memories USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 64)
        """)
        self.conn.commit()

    def get_rowid_by_memory_id(self, memory_id: str) -> Optional[int]:
        """Get the primary key (id) for a memory by its memory_id.

        Args:
            memory_id: UUID string of the memory

        Returns:
            Row id or None if not found
        """
        if not self.user_id:
            return None
        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                SELECT id FROM memories
                WHERE user_id = %s AND memory_id LIKE %s
            """, (self.user_id, memory_id + "%"))
            row = cursor.fetchone()
            self.conn.commit()
            return row[0] if row else None
        except Exception:
            self.conn.rollback()
            raise

    def get_embedding_dim(self) -> Optional[int]:
        """Get stored embedding dimension from meta table.

        Returns:
            Embedding dimension or None if not set
        """
        if not self.user_id:
            return None
        val = self.get_meta("embedding_dim")
        return int(val) if val is not None else None

    def set_embedding_dim(self, dim: int) -> None:
        """Store embedding dimension in meta table.

        Args:
            dim: Embedding dimension
        """
        if not self.user_id:
            return
        self.set_meta("embedding_dim", str(dim))

    def ensure_vec_table(self, dim: int) -> None:
        """Ensure vector operations are ready (dimension check).

        Args:
            dim: Embedding dimension
        """
        stored_dim = self.get_embedding_dim()
        if stored_dim is None:
            self.set_embedding_dim(dim)
        elif stored_dim != dim:
            from memory.db import DimensionMismatchError
            raise DimensionMismatchError(stored_dim, dim)

    def insert_memory(self, mem: Memory, details: Optional[str] = None) -> int:
        """Insert a memory into the database.

        Args:
            mem: Memory object to insert
            details: Optional full details/body text

        Returns:
            The row id of inserted memory
        """
        if not self.user_id:
            raise ValueError("user_id required for insert_memory")

        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                INSERT INTO memories (
                    user_id, memory_id, title, what, why, impact, tags, category, project,
                    source, agent, related_files, file_path, section_anchor, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                self.user_id, mem.id, mem.title, mem.what, mem.why, mem.impact,
                mem.tags, mem.category, mem.project, mem.source, mem.agent,
                mem.related_files, mem.file_path, mem.section_anchor,
                mem.created_at, mem.updated_at
            ))

            rowid = cursor.fetchone()[0]

            # Insert details if provided
            if details:
                cursor.execute("""
                    INSERT INTO memory_details (user_id, memory_id, body)
                    VALUES (%s, %s, %s)
                """, (self.user_id, mem.id, details))

            self.conn.commit()
            return rowid
        except Exception:
            self.conn.rollback()
            raise

    def insert_vector(self, rowid: int, embedding: list[float]) -> None:
        """Insert/update embedding vector for a memory.

        Args:
            rowid: The row id of the memory
            embedding: Embedding vector
        """
        if not self.user_id:
            return

        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                UPDATE memories
                SET embedding = %s
                WHERE id = %s AND user_id = %s
            """, (embedding, rowid, self.user_id))

            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_memory(self, memory_id: str) -> Optional[dict]:
        """Get a memory by ID.

        Args:
            memory_id: Memory ID to retrieve

        Returns:
            Dictionary with memory data or None if not found
        """
        if not self.user_id:
            return None

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            cursor.execute("""
                SELECT m.*,
                       EXISTS(SELECT 1 FROM memory_details WHERE user_id = m.user_id AND memory_id = m.memory_id) as has_details
                FROM memories m
                WHERE m.user_id = %s AND m.memory_id = %s
            """, (self.user_id, memory_id))

            row = cursor.fetchone()
            self.conn.commit()
            if row:
                return _normalize_row(row)
            return None
        except Exception:
            self.conn.rollback()
            raise

    def get_details(self, memory_id: str) -> Optional[MemoryDetail]:
        """Get full details for a memory.

        Args:
            memory_id: Memory ID

        Returns:
            MemoryDetail object or None if no details exist
        """
        if not self.user_id:
            return None

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            cursor.execute("""
                SELECT memory_id, body
                FROM memory_details
                WHERE user_id = %s AND memory_id LIKE %s
            """, (self.user_id, memory_id + "%"))

            row = cursor.fetchone()
            self.conn.commit()
            if row:
                return MemoryDetail(memory_id=row["memory_id"], body=row["body"])
            return None
        except Exception:
            self.conn.rollback()
            raise

    def update_memory(
        self,
        memory_id: str,
        what: str | None = None,
        why: str | None = None,
        impact: str | None = None,
        tags: list[str] | None = None,
        details_append: str | None = None,
    ) -> bool:
        """Update an existing memory's fields.

        Args:
            memory_id: Full UUID or prefix
            what: New what text
            why: New why text
            impact: New impact text
            tags: New tag list
            details_append: Text to append to details

        Returns:
            True if updated, False if not found
        """
        if not self.user_id:
            return False

        cursor = self._safe_cursor()
        try:
            # Resolve full ID from prefix
            cursor.execute("""
                SELECT memory_id, id FROM memories
                WHERE user_id = %s AND memory_id LIKE %s
            """, (self.user_id, memory_id + "%"))
            row = cursor.fetchone()
            if not row:
                self.conn.commit()
                return False

            full_id = row[0]
            rowid = row[1]

            # Build UPDATE query dynamically
            from datetime import datetime, timezone
            sets = ["updated_count = updated_count + 1", "updated_at = %s"]
            params = [datetime.now(timezone.utc).isoformat()]

            if what is not None:
                sets.append("what = %s")
                params.append(what)
            if why is not None:
                sets.append("why = %s")
                params.append(why)
            if impact is not None:
                sets.append("impact = %s")
                params.append(impact)
            if tags is not None:
                sets.append("tags = %s")
                params.append(tags)

            params.extend([self.user_id, full_id])
            cursor.execute(
                f"UPDATE memories SET {', '.join(sets)} WHERE user_id = %s AND memory_id = %s",
                params
            )

            # Handle details append
            if details_append:
                cursor.execute("""
                    SELECT body FROM memory_details
                    WHERE user_id = %s AND memory_id = %s
                """, (self.user_id, full_id))
                existing = cursor.fetchone()
                if existing:
                    new_body = existing[0] + "\n\n" + details_append
                    cursor.execute("""
                        UPDATE memory_details SET body = %s
                        WHERE user_id = %s AND memory_id = %s
                    """, (new_body, self.user_id, full_id))
                else:
                    cursor.execute("""
                        INSERT INTO memory_details (user_id, memory_id, body)
                        VALUES (%s, %s, %s)
                    """, (self.user_id, full_id, details_append))

            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID or prefix.

        Args:
            memory_id: Full UUID or prefix

        Returns:
            True if deleted, False if not found
        """
        if not self.user_id:
            return False

        cursor = self._safe_cursor()
        try:
            # Resolve full ID
            cursor.execute("""
                SELECT memory_id FROM memories
                WHERE user_id = %s AND memory_id LIKE %s
            """, (self.user_id, memory_id + "%"))
            row = cursor.fetchone()
            if not row:
                self.conn.commit()
                return False

            full_id = row[0]
            cursor.execute("""
                DELETE FROM memory_details
                WHERE user_id = %s AND memory_id = %s
            """, (self.user_id, full_id))
            cursor.execute("""
                DELETE FROM memories
                WHERE user_id = %s AND memory_id = %s
            """, (self.user_id, full_id))

            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def fts_search(
        self,
        query: str,
        limit: int = 10,
        project: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict]:
        """Search memories using PostgreSQL full-text search.

        Args:
            query: Search query
            limit: Max results
            project: Optional project filter
            source: Optional source filter
            agent: Optional agent role filter

        Returns:
            List of memory dictionaries with scores
        """
        if not self.user_id:
            return []

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            where_clauses = ["m.user_id = %s"]
            where_params = [self.user_id]

            if project:
                where_clauses.append("m.project = %s")
                where_params.append(project)

            if source:
                where_clauses.append("m.source = %s")
                where_params.append(source)

            if agent:
                where_clauses.append("m.agent = %s")
                where_params.append(agent)

            where_clause = " AND ".join(where_clauses)
            # Param order must match SQL %s order:
            # 1. ts_rank(plainto_tsquery) in SELECT
            # 2. WHERE clauses (user_id, project?, source?, agent?)
            # 3. fts @@ plainto_tsquery in WHERE
            # 4. LIMIT
            params = [query] + where_params + [query, limit]

            cursor.execute(f"""
                SELECT m.*,
                       ts_rank(m.fts, plainto_tsquery('english', %s)) as score,
                       EXISTS(SELECT 1 FROM memory_details WHERE user_id = m.user_id AND memory_id = m.memory_id) as has_details
                FROM memories m
                WHERE {where_clause}
                  AND m.fts @@ plainto_tsquery('english', %s)
                ORDER BY score DESC
                LIMIT %s
            """, params)

            results = [_normalize_row(row) for row in cursor.fetchall()]
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

    def vector_search(
        self,
        query_embedding: list[float],
        limit: int = 10,
        project: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict]:
        """Search memories using vector similarity.

        Args:
            query_embedding: Query embedding vector
            limit: Max results
            project: Optional project filter
            source: Optional source filter
            agent: Optional agent role filter

        Returns:
            List of memory dictionaries with similarity scores
        """
        if not self.user_id:
            return []

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            where_clauses = ["m.user_id = %s", "m.embedding IS NOT NULL"]
            where_params = [self.user_id]

            if project:
                where_clauses.append("m.project = %s")
                where_params.append(project)

            if source:
                where_clauses.append("m.source = %s")
                where_params.append(source)

            if agent:
                where_clauses.append("m.agent = %s")
                where_params.append(agent)

            where_clause = " AND ".join(where_clauses)
            # Param order must match SQL %s order:
            # 1. (m.embedding <=> %s) in SELECT
            # 2. WHERE clauses (user_id, project?, source?, agent?)
            # 3. ORDER BY m.embedding <=> %s
            # 4. LIMIT
            params = [query_embedding] + where_params + [query_embedding, limit]

            cursor.execute(f"""
                SELECT m.*,
                       1 - (m.embedding <=> %s) as score,
                       EXISTS(SELECT 1 FROM memory_details WHERE user_id = m.user_id AND memory_id = m.memory_id) as has_details
                FROM memories m
                WHERE {where_clause}
                ORDER BY m.embedding <=> %s
                LIMIT %s
            """, params)

            results = [_normalize_row(row) for row in cursor.fetchall()]
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

    def list_recent(
        self,
        limit: int = 10,
        project: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> list[dict]:
        """List recent memories ordered by creation date descending.

        Args:
            limit: Max results
            project: Optional project filter
            source: Optional source filter
            agent: Optional agent role filter

        Returns:
            List of memory dictionaries
        """
        if not self.user_id:
            return []

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            where_clauses = ["m.user_id = %s"]
            params = [self.user_id]

            if project:
                where_clauses.append("m.project = %s")
                params.append(project)

            if source:
                where_clauses.append("m.source = %s")
                params.append(source)

            if agent:
                where_clauses.append("m.agent = %s")
                params.append(agent)

            where_clause = " AND ".join(where_clauses)
            params.append(limit)

            cursor.execute(f"""
                SELECT m.memory_id as id, m.title, m.category, m.tags, m.project, m.source, m.created_at,
                       EXISTS(SELECT 1 FROM memory_details WHERE user_id = m.user_id AND memory_id = m.memory_id) as has_details
                FROM memories m
                WHERE {where_clause}
                ORDER BY m.created_at DESC
                LIMIT %s
            """, params)

            results = [_normalize_row(row) for row in cursor.fetchall()]
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

    def list_all_for_reindex(self) -> list[dict]:
        """List all memories for re-embedding.

        Returns:
            List of dicts with id, title, what, why, impact, tags
        """
        if not self.user_id:
            return []

        cursor = self._safe_cursor(dict_cursor=True)
        try:
            cursor.execute("""
                SELECT id as rowid, title, what, why, impact, tags
                FROM memories
                WHERE user_id = %s
                ORDER BY id
            """, (self.user_id,))
            results = [_normalize_row(row) for row in cursor.fetchall()]
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

    def count_memories(
        self,
        project: Optional[str] = None,
        source: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> int:
        """Count total memories.

        Args:
            project: Optional project filter
            source: Optional source filter
            agent: Optional agent role filter

        Returns:
            Total count
        """
        if not self.user_id:
            return 0

        cursor = self._safe_cursor()
        try:
            where_clauses = ["user_id = %s"]
            params = [self.user_id]

            if project:
                where_clauses.append("project = %s")
                params.append(project)

            if source:
                where_clauses.append("source = %s")
                params.append(source)

            if agent:
                where_clauses.append("agent = %s")
                params.append(agent)

            where_clause = " AND ".join(where_clauses)

            cursor.execute(f"""
                SELECT COUNT(*) FROM memories WHERE {where_clause}
            """, params)

            result = cursor.fetchone()[0]
            self.conn.commit()
            return result
        except Exception:
            self.conn.rollback()
            raise

    def set_meta(self, key: str, value: str) -> None:
        """Set metadata key-value pair.

        Args:
            key: Metadata key
            value: Metadata value
        """
        if not self.user_id:
            return

        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                INSERT INTO meta (user_id, key, value)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
            """, (self.user_id, key, value))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def get_meta(self, key: str) -> Optional[str]:
        """Get metadata value by key.

        Args:
            key: Metadata key

        Returns:
            Metadata value or None
        """
        if not self.user_id:
            return None

        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                SELECT value FROM meta
                WHERE user_id = %s AND key = %s
            """, (self.user_id, key))

            row = cursor.fetchone()
            self.conn.commit()
            return row[0] if row else None
        except Exception:
            self.conn.rollback()
            raise

    def close(self) -> None:
        """Close database connection."""
        self.conn.close()

    # Admin methods (no user_id scoping)

    def create_user(self, name: str) -> tuple[int, str]:
        """Create a new user (admin operation).

        Args:
            name: User name

        Returns:
            Tuple of (user_id, token)
        """
        cursor = self._safe_cursor()
        try:
            cursor.execute("""
                INSERT INTO users (name)
                VALUES (%s)
                RETURNING id, token
            """, (name,))
            row = cursor.fetchone()
            self.conn.commit()
            return row[0], row[1]
        except Exception:
            self.conn.rollback()
            raise

    def list_users(self) -> list[dict]:
        """List all users (admin operation).

        Returns:
            List of user dicts
        """
        cursor = self._safe_cursor(dict_cursor=True)
        try:
            cursor.execute("""
                SELECT id, name, created_at
                FROM users
                ORDER BY id
            """)
            results = [_normalize_row(row) for row in cursor.fetchall()]
            self.conn.commit()
            return results
        except Exception:
            self.conn.rollback()
            raise

    def get_user_by_token(self, token: str) -> Optional[dict]:
        """Get user by token (admin/auth operation).

        Args:
            token: User token

        Returns:
            User dict or None
        """
        cursor = self._safe_cursor(dict_cursor=True)
        try:
            cursor.execute("""
                SELECT id, name, created_at
                FROM users
                WHERE token = %s
            """, (token,))
            row = cursor.fetchone()
            self.conn.commit()
            if row:
                return _normalize_row(row)
            return None
        except Exception:
            self.conn.rollback()
            raise
