#!/usr/bin/env python3
"""Set up the OG context store database.

Creates the database, enables extensions (pgvector, Apache AGE),
and builds all tables and indexes for triple-modality context retrieval.

Usage:
    python scripts/setup-db.py              # default: localhost:5432, database 'og'
    python scripts/setup-db.py --drop       # drop and recreate everything
    python scripts/setup-db.py --check      # verify setup without modifying

Environment:
    OG_DB__HOST          (default: localhost)
    OG_DB__PORT          (default: 5432)
    OG_DB__NAME          (default: og)
    OG_DB__USER          (default: og)
    OG_DB__PASSWORD      (default: og)
    OG_DB__ADMIN_DSN     (default: postgresql://postgres@localhost:5432/postgres)
"""

import argparse
import os
import sys

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_HOST = os.getenv("OG_DB__HOST", "localhost")
DB_PORT = int(os.getenv("OG_DB__PORT", "5432"))
DB_NAME = os.getenv("OG_DB__NAME", "og")
DB_USER = os.getenv("OG_DB__USER", "og")
DB_PASSWORD = os.getenv("OG_DB__PASSWORD", "og")
ADMIN_DSN = os.getenv(
    "OG_DB__ADMIN_DSN",
    f"postgresql://postgres@{DB_HOST}:{DB_PORT}/postgres",
)

EMBEDDING_DIMS = 1024  # mxbai-embed-large via Ollama


# ---------------------------------------------------------------------------
# SQL definitions
# ---------------------------------------------------------------------------

EXTENSIONS_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
"""

# Load AGE into the search path for the session so CREATE/ALTER work.
AGE_SEARCH_PATH = "SET search_path = ag_catalog, public;"

TABLES_SQL = """
-- ---------------------------------------------------------------------------
-- Context chunks: the atomic unit of stored knowledge
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS context_chunks (
    id              BIGSERIAL PRIMARY KEY,
    project_id      VARCHAR(255) NOT NULL,
    chunk_type      VARCHAR(64)  NOT NULL,  -- decision, correction, constraint, fact, observation, pattern
    text            TEXT         NOT NULL,
    embedding       vector({dims}),
    text_search     tsvector     GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    source_session  VARCHAR(255),           -- session that produced this chunk
    source_type     VARCHAR(64),            -- pre_compact, manual, agent_extract, session_start
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_accessed   TIMESTAMPTZ,
    access_count    INT          NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Session events: replaces JSONL append-only logs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS session_events (
    id              BIGSERIAL    PRIMARY KEY,
    session_id      VARCHAR(255) NOT NULL,
    project_id      VARCHAR(255) NOT NULL,
    event_type      VARCHAR(64)  NOT NULL,  -- session_start, user_message, assistant_message, tool_use, tool_result
    content         JSONB        NOT NULL DEFAULT '{{}}'::jsonb,
    token_count     INT,                    -- token estimate for this event
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Budget ledger: append-only spending journal
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS budget_ledger (
    id              BIGSERIAL    PRIMARY KEY,
    project_id      VARCHAR(255) NOT NULL,
    session_id      VARCHAR(255),
    model           VARCHAR(255) NOT NULL,
    input_tokens    INT          NOT NULL DEFAULT 0,
    output_tokens   INT          NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6) NOT NULL,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);
""".format(dims=EMBEDDING_DIMS)

INDEXES_SQL = """
-- ---------------------------------------------------------------------------
-- pgvector HNSW index: semantic similarity search
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
    ON context_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- ---------------------------------------------------------------------------
-- GIN index: full-text keyword search
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chunks_text_search
    ON context_chunks
    USING gin (text_search);

-- ---------------------------------------------------------------------------
-- B-tree indexes: filtered queries and lookups
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chunks_project
    ON context_chunks (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chunks_type
    ON context_chunks (project_id, chunk_type);

CREATE INDEX IF NOT EXISTS idx_events_session
    ON session_events (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_events_project
    ON session_events (project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_budget_project
    ON budget_ledger (project_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Unique index: deduplication (functional expression index)
-- ---------------------------------------------------------------------------
CREATE UNIQUE INDEX IF NOT EXISTS uq_chunk_text
    ON context_chunks (project_id, md5(text));
"""

# AGE graph setup — creates the graph and vertex/edge labels.
GRAPH_SQL = """
SELECT * FROM ag_catalog.create_graph('og_knowledge');

SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'Decision');
SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'Correction');
SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'Constraint');
SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'CodeEntity');
SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'Session');
SELECT * FROM ag_catalog.create_vlabel('og_knowledge', 'Pattern');

SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'REJECTED_IN_FAVOR_OF');
SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'DEPENDS_ON');
SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'DISCOVERED_IN');
SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'CONTRADICTS');
SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'CAUSED_BY');
SELECT * FROM ag_catalog.create_elabel('og_knowledge', 'SUPERSEDES');
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def connect_admin():
    """Connect to the admin database (postgres) for CREATE DATABASE."""
    conn = psycopg2.connect(ADMIN_DSN)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def connect_og():
    """Connect to the OG database as the OG role."""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def connect_og_admin():
    """Connect to the OG database as the admin (superuser) for DDL operations."""
    admin_dsn = ADMIN_DSN.rsplit("/", 1)[0] + f"/{DB_NAME}"
    return psycopg2.connect(admin_dsn)


def db_exists(cur):
    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
    return cur.fetchone() is not None


def role_exists(cur):
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (DB_USER,))
    return cur.fetchone() is not None


def graph_exists(cur):
    cur.execute(
        "SELECT 1 FROM ag_catalog.ag_graph WHERE name = %s", ("og_knowledge",)
    )
    return cur.fetchone() is not None


def print_ok(msg):
    print(f"  \033[32m✓\033[0m {msg}")


def print_skip(msg):
    print(f"  \033[33m-\033[0m {msg} (already exists)")


def print_info(msg):
    print(f"  \033[36m→\033[0m {msg}")


def print_err(msg):
    print(f"  \033[31m✗\033[0m {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def create_role_and_database(drop=False):
    """Create the OG role and database via the admin connection."""
    print("\n1. Database & role")
    conn = connect_admin()
    cur = conn.cursor()

    if drop:
        print_info(f"Dropping database '{DB_NAME}' if it exists")
        cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(DB_NAME)))
        print_ok(f"Dropped database '{DB_NAME}'")

    if not role_exists(cur):
        cur.execute(
            sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(
                sql.Identifier(DB_USER)
            ),
            (DB_PASSWORD,),
        )
        print_ok(f"Created role '{DB_USER}'")
    else:
        print_skip(f"Role '{DB_USER}'")

    if not db_exists(cur):
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(DB_NAME), sql.Identifier(DB_USER)
            )
        )
        print_ok(f"Created database '{DB_NAME}'")
    else:
        print_skip(f"Database '{DB_NAME}'")

    cur.close()
    conn.close()


def create_extensions():
    """Enable pgvector and AGE extensions (requires superuser on the OG database)."""
    print("\n2. Extensions")
    conn = connect_og_admin()
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    for line in EXTENSIONS_SQL.strip().split("\n"):
        line = line.strip()
        if line and not line.startswith("--"):
            cur.execute(line)
            ext = line.split("EXISTS")[-1].strip().rstrip(";")
            print_ok(f"Extension {ext}")

    # Grant AGE schema usage to our role
    cur.execute(f"GRANT USAGE ON SCHEMA ag_catalog TO {DB_USER};")
    print_ok(f"Granted ag_catalog usage to '{DB_USER}'")

    cur.close()
    conn.close()


def create_tables():
    """Create relational tables."""
    print("\n3. Tables")
    conn = connect_og_admin()
    cur = conn.cursor()
    cur.execute(TABLES_SQL)
    conn.commit()
    print_ok("context_chunks")
    print_ok("session_events")
    print_ok("budget_ledger")
    cur.close()
    conn.close()


def create_indexes():
    """Create HNSW, GIN, and B-tree indexes."""
    print("\n4. Indexes")
    conn = connect_og_admin()
    cur = conn.cursor()
    cur.execute(INDEXES_SQL)
    conn.commit()
    print_ok("idx_chunks_embedding (HNSW, cosine, m=16, ef_construction=200)")
    print_ok("idx_chunks_text_search (GIN, tsvector)")
    print_ok("idx_chunks_project, idx_chunks_type (B-tree)")
    print_ok("idx_events_session, idx_events_project (B-tree)")
    print_ok("idx_budget_project (B-tree)")
    cur.close()
    conn.close()


def create_graph():
    """Create the AGE knowledge graph with vertex and edge labels."""
    print("\n5. Knowledge graph (Apache AGE)")
    conn = connect_og_admin()
    cur = conn.cursor()
    cur.execute(AGE_SEARCH_PATH)

    if graph_exists(cur):
        print_skip("Graph 'og_knowledge'")
        cur.close()
        conn.close()
        return

    for statement in GRAPH_SQL.strip().split("\n"):
        statement = statement.strip()
        if statement and not statement.startswith("--"):
            cur.execute(statement)

    conn.commit()
    print_ok("Graph 'og_knowledge'")
    print_ok("Vertex labels: Decision, Correction, Constraint, CodeEntity, Session, Pattern")
    print_ok("Edge labels: REJECTED_IN_FAVOR_OF, DEPENDS_ON, DISCOVERED_IN, CONTRADICTS, CAUSED_BY, SUPERSEDES")
    cur.close()
    conn.close()


def grant_permissions():
    """Grant the OG role full access to all tables and sequences."""
    print("\n6. Permissions")
    conn = connect_og_admin()
    cur = conn.cursor()
    cur.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {DB_USER};")
    cur.execute(f"GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO {DB_USER};")
    cur.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {DB_USER};")
    cur.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {DB_USER};")
    # AGE schema access
    cur.execute(f"GRANT ALL ON SCHEMA ag_catalog TO {DB_USER};")
    cur.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA ag_catalog TO {DB_USER};")
    # AGE graph schema — each graph creates its own schema
    cur.execute(f"GRANT ALL ON SCHEMA og_knowledge TO {DB_USER};")
    cur.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA og_knowledge TO {DB_USER};")
    conn.commit()
    print_ok(f"Granted full access to role '{DB_USER}'")
    cur.close()
    conn.close()


def check_setup():
    """Verify that everything is set up correctly."""
    print("\nVerification")
    errors = 0

    # 1. Connect
    try:
        conn = connect_og()
        print_ok(f"Connected to {DB_NAME} on {DB_HOST}:{DB_PORT}")
    except Exception as e:
        print_err(f"Cannot connect: {e}")
        return False

    cur = conn.cursor()

    # 2. Extensions
    cur.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector', 'age') ORDER BY extname")
    exts = [row[0] for row in cur.fetchall()]
    for ext in ("age", "vector"):
        if ext in exts:
            print_ok(f"Extension '{ext}' installed")
        else:
            print_err(f"Extension '{ext}' NOT installed")
            errors += 1

    # 3. Tables
    cur.execute("""
        SELECT tablename FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename IN ('context_chunks', 'session_events', 'budget_ledger')
        ORDER BY tablename
    """)
    tables = [row[0] for row in cur.fetchall()]
    for t in ("budget_ledger", "context_chunks", "session_events"):
        if t in tables:
            print_ok(f"Table '{t}'")
        else:
            print_err(f"Table '{t}' NOT found")
            errors += 1

    # 4. HNSW index
    cur.execute("""
        SELECT indexname, indexdef FROM pg_indexes
        WHERE tablename = 'context_chunks' AND indexdef LIKE '%hnsw%'
    """)
    hnsw = cur.fetchall()
    if hnsw:
        print_ok(f"HNSW index: {hnsw[0][0]}")
    else:
        print_err("HNSW index NOT found on context_chunks.embedding")
        errors += 1

    # 5. AGE graph
    cur.execute(AGE_SEARCH_PATH)
    if graph_exists(cur):
        print_ok("Graph 'og_knowledge'")
    else:
        print_err("Graph 'og_knowledge' NOT found")
        errors += 1

    # 6. Embedding dimension check
    cur.execute("""
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'context_chunks'::regclass AND attname = 'embedding'
    """)
    row = cur.fetchone()
    if row:
        dims = row[0]
        print_ok(f"Embedding column: vector({dims})")
    else:
        print_err("Embedding column NOT found")
        errors += 1

    cur.close()
    conn.close()

    if errors:
        print(f"\n  {errors} issue(s) found.")
        return False
    else:
        print("\n  All checks passed.")
        return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Set up the OG context store database.")
    parser.add_argument("--drop", action="store_true", help="Drop and recreate the database")
    parser.add_argument("--check", action="store_true", help="Verify setup without modifying")
    args = parser.parse_args()

    print("OG Context Store — Database Setup")
    print(f"  Target: {DB_HOST}:{DB_PORT}/{DB_NAME} (role: {DB_USER})")
    print(f"  Embedding: vector({EMBEDDING_DIMS}) — mxbai-embed-large via Ollama")

    if args.check:
        ok = check_setup()
        sys.exit(0 if ok else 1)

    try:
        create_role_and_database(drop=args.drop)
        create_extensions()
        create_tables()
        create_indexes()
        create_graph()
        grant_permissions()
        print("\n" + "=" * 50)
        check_setup()
    except psycopg2.OperationalError as e:
        print_err(f"Connection failed: {e}")
        print_info("Is PostgreSQL running? Check: pg_isready -h localhost -p 5432")
        sys.exit(1)
    except psycopg2.Error as e:
        print_err(f"Database error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
