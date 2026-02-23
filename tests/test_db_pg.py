"""Tests for PostgreSQL database layer with pgvector.

These tests connect to a real PostgreSQL instance.
Set TEST_PG_URL env var to run them:
  TEST_PG_URL=postgresql://postgres:password@localhost:5432/memory_test

Tests are skipped if TEST_PG_URL is not set or PG is unreachable.
"""

import os
import json

import pytest

from memory.models import Memory, MemoryDetail, RawMemoryInput

# Skip entire module if PG dependencies or connection unavailable
pg_url = os.environ.get("TEST_PG_URL")

try:
    import psycopg2
    from pgvector.psycopg2 import register_vector
    HAS_PG_DEPS = True
except ImportError:
    HAS_PG_DEPS = False

# Check if PG is reachable
PG_REACHABLE = False
if HAS_PG_DEPS and pg_url:
    try:
        conn = psycopg2.connect(pg_url)
        conn.close()
        PG_REACHABLE = True
    except Exception:
        pass

pytestmark = pytest.mark.skipif(
    not PG_REACHABLE,
    reason="PostgreSQL not available (set TEST_PG_URL env var)"
)


@pytest.fixture
def pg_db():
    """Create a MemoryDBPostgres instance with a test user, clean up after."""
    from memory.db_pg import MemoryDBPostgres

    # Create admin connection (no user_id) to set up test user
    admin_db = MemoryDBPostgres(pg_url, user_id=None)

    # Create test user (or reuse existing)
    cursor = admin_db._safe_cursor()
    cursor.execute("SELECT id FROM users WHERE name = 'test_runner'")
    row = cursor.fetchone()
    if row:
        test_user_id = row[0]
    else:
        test_user_id, _ = admin_db.create_user("test_runner")
    admin_db.conn.commit()
    admin_db.close()

    # Create user-scoped DB instance
    db = MemoryDBPostgres(pg_url, user_id=test_user_id)

    yield db

    # Cleanup: delete all test user's memories
    cleanup_cursor = db._safe_cursor()
    cleanup_cursor.execute("DELETE FROM memory_details WHERE user_id = %s", (test_user_id,))
    cleanup_cursor.execute("DELETE FROM memories WHERE user_id = %s", (test_user_id,))
    cleanup_cursor.execute("DELETE FROM meta WHERE user_id = %s", (test_user_id,))
    db.conn.commit()
    db.close()


@pytest.fixture
def sample_memory():
    """Create a sample memory for testing."""
    raw = RawMemoryInput(
        title="Test Authentication Bug",
        what="Fixed token validation in auth middleware",
        why="Users were getting logged out unexpectedly",
        impact="Improved session stability by 95%",
        tags=["auth", "security", "bug-fix"],
        category="bug",
        related_files=["src/auth/middleware.py", "tests/test_auth.py"],
        source="claude-code",
        agent="developer",
    )
    return Memory.from_raw(raw, project="test-project", file_path="memories/2024-01.md")


@pytest.fixture
def sample_detail(sample_memory):
    """Create sample memory detail."""
    return MemoryDetail(
        memory_id=sample_memory.id,
        body="Detailed analysis of the authentication bug...\n\nRoot cause was..."
    )


class TestPGInsertAndRetrieve:
    """Test basic insert and retrieval operations."""

    def test_insert_and_get_memory(self, pg_db, sample_memory):
        """Test inserting and retrieving a memory."""
        rowid = pg_db.insert_memory(sample_memory)
        assert rowid > 0

        result = pg_db.get_memory(sample_memory.id)
        assert result is not None
        assert result["memory_id"] == sample_memory.id
        assert result["title"] == sample_memory.title
        assert result["what"] == sample_memory.what
        assert result["why"] == sample_memory.why
        assert result["impact"] == sample_memory.impact
        assert result["category"] == sample_memory.category
        assert result["project"] == sample_memory.project
        assert result["source"] == sample_memory.source
        assert result["agent"] == sample_memory.agent

    def test_insert_with_details(self, pg_db, sample_memory, sample_detail):
        """Test inserting memory with details and retrieving them."""
        rowid = pg_db.insert_memory(sample_memory, details=sample_detail.body)
        assert rowid > 0

        detail = pg_db.get_details(sample_memory.id)
        assert detail is not None
        assert detail.memory_id == sample_memory.id
        assert detail.body == sample_detail.body

    def test_get_details_with_prefix(self, pg_db, sample_memory, sample_detail):
        """Test that get_details works with a UUID prefix."""
        pg_db.insert_memory(sample_memory, details=sample_detail.body)

        prefix = sample_memory.id[:8]
        detail = pg_db.get_details(prefix)
        assert detail is not None
        assert detail.memory_id == sample_memory.id

    def test_get_details_returns_none_when_no_details(self, pg_db, sample_memory):
        """Test that get_details returns None when no details exist."""
        pg_db.insert_memory(sample_memory)
        detail = pg_db.get_details(sample_memory.id)
        assert detail is None

    def test_has_details_flag(self, pg_db, sample_memory):
        """Test has_details flag is set correctly."""
        pg_db.insert_memory(sample_memory)
        result = pg_db.get_memory(sample_memory.id)
        assert result["has_details"] is False

        # Insert another with details
        raw = RawMemoryInput(
            title="Memory with Details",
            what="This has details",
            category="context",
        )
        memory_with_details = Memory.from_raw(raw, project="test-project", file_path="test.md")
        pg_db.insert_memory(memory_with_details, details="Detailed information here")

        result_with_details = pg_db.get_memory(memory_with_details.id)
        assert result_with_details["has_details"] is True

    def test_insert_memory_requires_user_id(self, sample_memory):
        """Test that insert_memory raises without user_id."""
        from memory.db_pg import MemoryDBPostgres
        db = MemoryDBPostgres(pg_url, user_id=None)

        with pytest.raises(ValueError, match="user_id required"):
            db.insert_memory(sample_memory)

        db.close()

    def test_tags_stored_as_array(self, pg_db, sample_memory):
        """Test that tags are stored as PG array, not JSON string."""
        pg_db.insert_memory(sample_memory)
        result = pg_db.get_memory(sample_memory.id)

        # PG returns tags as Python list directly
        assert isinstance(result["tags"], list)
        assert result["tags"] == ["auth", "security", "bug-fix"]


class TestPGSearch:
    """Test search operations."""

    def test_fts_search_finds_matching(self, pg_db, sample_memory):
        """Test FTS search finds matching memories."""
        pg_db.insert_memory(sample_memory)

        results = pg_db.fts_search("authentication", limit=10)
        assert len(results) > 0
        assert results[0]["memory_id"] == sample_memory.id
        assert results[0]["score"] > 0

    def test_fts_search_empty_for_no_matches(self, pg_db, sample_memory):
        """Test FTS search returns empty list when no matches."""
        pg_db.insert_memory(sample_memory)

        results = pg_db.fts_search("nonexistent_xyzzy", limit=10)
        assert len(results) == 0

    def test_fts_search_filter_by_project(self, pg_db):
        """Test FTS search filters by project."""
        for project in ["project-a", "project-b"]:
            raw = RawMemoryInput(
                title=f"{project} Memory",
                what=f"Content for {project}",
                category="context",
            )
            mem = Memory.from_raw(raw, project=project, file_path="test.md")
            pg_db.insert_memory(mem)

        results = pg_db.fts_search("Memory", limit=10, project="project-a")
        assert len(results) == 1
        assert results[0]["project"] == "project-a"

    def test_fts_search_filter_by_agent(self, pg_db):
        """Test FTS search filters by agent role."""
        for agent in ["developer", "architect"]:
            raw = RawMemoryInput(
                title=f"{agent} Decision",
                what=f"Decision by {agent}",
                category="decision",
                agent=agent,
            )
            mem = Memory.from_raw(raw, project="test", file_path="test.md")
            pg_db.insert_memory(mem)

        results = pg_db.fts_search("Decision", limit=10, agent="developer")
        assert len(results) == 1
        assert results[0]["agent"] == "developer"

    def test_vector_search(self, pg_db):
        """Test vector similarity search."""
        pg_db.ensure_vec_table(1536)

        # Insert two memories with different embeddings
        raw1 = RawMemoryInput(title="Database Schema", what="Schema design")
        mem1 = Memory.from_raw(raw1, project="test", file_path="test.md")
        rowid1 = pg_db.insert_memory(mem1)
        pg_db.insert_vector(rowid1, [1.0] * 1536)

        raw2 = RawMemoryInput(title="API Design", what="REST endpoints")
        mem2 = Memory.from_raw(raw2, project="test", file_path="test.md")
        rowid2 = pg_db.insert_memory(mem2)
        pg_db.insert_vector(rowid2, [0.0] * 1536)

        # Search with query similar to first
        results = pg_db.vector_search([0.9] * 1536, limit=2)
        assert len(results) == 2
        assert results[0]["title"] == "Database Schema"

    def test_list_recent(self, pg_db):
        """Test listing recent memories."""
        for i in range(3):
            raw = RawMemoryInput(title=f"Memory {i}", what=f"Content {i}")
            mem = Memory.from_raw(raw, project="test", file_path="test.md")
            pg_db.insert_memory(mem)

        results = pg_db.list_recent(limit=2)
        assert len(results) == 2

    def test_count_memories(self, pg_db):
        """Test counting memories."""
        assert pg_db.count_memories() == 0

        for i in range(3):
            raw = RawMemoryInput(title=f"Memory {i}", what=f"Content {i}")
            mem = Memory.from_raw(raw, project="test", file_path="test.md")
            pg_db.insert_memory(mem)

        assert pg_db.count_memories() == 3
        assert pg_db.count_memories(project="test") == 3
        assert pg_db.count_memories(project="nonexistent") == 0


class TestPGUpdateDelete:
    """Test update and delete operations."""

    def test_update_memory_fields(self, pg_db):
        """Test updating memory fields."""
        raw = RawMemoryInput(
            title="Original Title",
            what="Original what",
            why="Original why",
            tags=["tag1"],
            category="decision",
        )
        mem = Memory.from_raw(raw, project="test", file_path="test.md")
        pg_db.insert_memory(mem)

        updated = pg_db.update_memory(
            mem.id,
            what="Updated what",
            why="Updated why",
            impact="New impact",
            tags=["tag1", "tag2"],
        )
        assert updated is True

        result = pg_db.get_memory(mem.id)
        assert result["what"] == "Updated what"
        assert result["why"] == "Updated why"
        assert result["impact"] == "New impact"
        assert result["updated_count"] == 1
        assert result["tags"] == ["tag1", "tag2"]

    def test_update_memory_appends_details(self, pg_db):
        """Test appending to existing details."""
        raw = RawMemoryInput(
            title="With Details",
            what="Has details",
            category="bug",
        )
        mem = Memory.from_raw(raw, project="test", file_path="test.md")
        pg_db.insert_memory(mem, details="Original details")

        pg_db.update_memory(mem.id, details_append="Appended details")

        detail = pg_db.get_details(mem.id)
        assert "Original details" in detail.body
        assert "Appended details" in detail.body

    def test_delete_memory(self, pg_db, sample_memory, sample_detail):
        """Test deleting a memory removes all associated data."""
        pg_db.insert_memory(sample_memory, details=sample_detail.body)

        deleted = pg_db.delete_memory(sample_memory.id)
        assert deleted is True
        assert pg_db.get_memory(sample_memory.id) is None
        assert pg_db.get_details(sample_memory.id) is None

    def test_delete_memory_with_prefix(self, pg_db, sample_memory):
        """Test deleting by UUID prefix."""
        pg_db.insert_memory(sample_memory)

        prefix = sample_memory.id[:8]
        deleted = pg_db.delete_memory(prefix)
        assert deleted is True
        assert pg_db.get_memory(sample_memory.id) is None

    def test_delete_returns_false_for_nonexistent(self, pg_db):
        """Test delete returns False for unknown ID."""
        assert pg_db.delete_memory("nonexistent-id") is False


class TestPGMeta:
    """Test metadata operations."""

    def test_set_and_get_meta(self, pg_db):
        """Test setting and getting metadata."""
        pg_db.set_meta("test_key", "test_value")
        assert pg_db.get_meta("test_key") == "test_value"

    def test_get_meta_returns_none_for_missing(self, pg_db):
        """Test that missing meta key returns None."""
        assert pg_db.get_meta("nonexistent") is None

    def test_embedding_dim_storage(self, pg_db):
        """Test storing and retrieving embedding dimension."""
        pg_db.set_embedding_dim(1536)
        assert pg_db.get_embedding_dim() == 1536


class TestPGTransactionSafety:
    """Test transaction safety and error recovery."""

    def test_safe_cursor_recovers_from_error(self, pg_db):
        """Test that _safe_cursor rolls back aborted transactions."""
        cursor = pg_db._safe_cursor()

        # Intentionally cause an error
        try:
            cursor.execute("SELECT * FROM nonexistent_table_xyzzy")
        except Exception:
            pass

        # Transaction should be in error state (4)
        assert pg_db.conn.info.transaction_status == 4

        # _safe_cursor should recover
        cursor2 = pg_db._safe_cursor()
        cursor2.execute("SELECT 1")
        result = cursor2.fetchone()
        assert result[0] == 1

    def test_insert_after_failed_query(self, pg_db):
        """Test that insert works after a previously failed query."""
        cursor = pg_db._safe_cursor()

        # Cause an error
        try:
            cursor.execute("INVALID SQL STATEMENT")
        except Exception:
            pass

        # Insert should still work via _safe_cursor
        raw = RawMemoryInput(title="After Error", what="This should work")
        mem = Memory.from_raw(raw, project="test", file_path="test.md")
        rowid = pg_db.insert_memory(mem)
        assert rowid > 0

        result = pg_db.get_memory(mem.id)
        assert result is not None
        assert result["title"] == "After Error"

    def test_search_after_failed_query(self, pg_db, sample_memory):
        """Test that search works after a previously failed query."""
        pg_db.insert_memory(sample_memory)

        # Cause an error
        cursor = pg_db._safe_cursor()
        try:
            cursor.execute("SELECT * FROM nonexistent_table_xyzzy")
        except Exception:
            pass

        # FTS search should recover
        results = pg_db.fts_search("authentication", limit=10)
        assert len(results) > 0


class TestPGUserIsolation:
    """Test multi-user isolation."""

    def test_users_cannot_see_each_others_memories(self):
        """Test that memories are isolated per user."""
        from memory.db_pg import MemoryDBPostgres

        # Create two users
        admin = MemoryDBPostgres(pg_url, user_id=None)

        cursor = admin._safe_cursor()
        cursor.execute("SELECT id FROM users WHERE name = 'test_user_a'")
        row = cursor.fetchone()
        if row:
            user_a_id = row[0]
        else:
            user_a_id, _ = admin.create_user("test_user_a")

        cursor.execute("SELECT id FROM users WHERE name = 'test_user_b'")
        row = cursor.fetchone()
        if row:
            user_b_id = row[0]
        else:
            user_b_id, _ = admin.create_user("test_user_b")

        admin.conn.commit()
        admin.close()

        # User A saves a memory
        db_a = MemoryDBPostgres(pg_url, user_id=user_a_id)
        raw_a = RawMemoryInput(title="User A Secret", what="Only for user A")
        mem_a = Memory.from_raw(raw_a, project="test", file_path="test.md")
        db_a.insert_memory(mem_a)

        # User B should not see User A's memory
        db_b = MemoryDBPostgres(pg_url, user_id=user_b_id)
        result = db_b.get_memory(mem_a.id)
        assert result is None

        results_b = db_b.fts_search("Secret", limit=10)
        assert len(results_b) == 0

        assert db_b.count_memories() == 0

        # Cleanup
        cleanup_a = db_a._safe_cursor()
        cleanup_a.execute("DELETE FROM memories WHERE user_id = %s", (user_a_id,))
        db_a.conn.commit()

        cleanup_b = db_b._safe_cursor()
        cleanup_b.execute("DELETE FROM memories WHERE user_id = %s", (user_b_id,))
        db_b.conn.commit()

        db_a.close()
        db_b.close()


class TestPGReindex:
    """Test reindex operations."""

    def test_list_all_for_reindex(self, pg_db):
        """Test listing all memories for reindex."""
        for i in range(3):
            raw = RawMemoryInput(title=f"Memory {i}", what=f"Content {i}")
            mem = Memory.from_raw(raw, project="test", file_path="test.md")
            pg_db.insert_memory(mem)

        memories = pg_db.list_all_for_reindex()
        assert len(memories) == 3
        assert all("rowid" in m for m in memories)
        assert all("title" in m for m in memories)

    def test_drop_and_recreate_vec_index(self, pg_db):
        """Test dropping and recreating vector index."""
        pg_db.ensure_vec_table(1536)
        assert pg_db.has_vec_table()

        pg_db.drop_vec_table()
        # has_vec_table always returns True for PG
        # but embeddings should be nulled

        pg_db._create_vec_table(1536)
        assert pg_db.has_vec_table()

    def test_get_rowid_by_memory_id(self, pg_db, sample_memory):
        """Test getting rowid by memory_id."""
        expected_rowid = pg_db.insert_memory(sample_memory)

        rowid = pg_db.get_rowid_by_memory_id(sample_memory.id)
        assert rowid == expected_rowid

        # Prefix should also work
        rowid_prefix = pg_db.get_rowid_by_memory_id(sample_memory.id[:8])
        assert rowid_prefix == expected_rowid

        # Nonexistent should return None
        assert pg_db.get_rowid_by_memory_id("nonexistent") is None
