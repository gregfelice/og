"""MCP server exposing context_recall and context_store tools."""

from __future__ import annotations

import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger(__name__)

CONTEXT_RECALL_TOOL = Tool(
    name="context_recall",
    description=(
        "Search the OG context store for relevant knowledge using triple-modality retrieval "
        "(semantic similarity, keyword search, and knowledge graph traversal). "
        "Returns ranked text chunks."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query",
            },
            "project_id": {
                "type": "string",
                "description": "Project identifier (default: 'default')",
                "default": "default",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Code entities or concepts for graph-boosted retrieval",
                "default": [],
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (default: 10)",
                "default": 10,
            },
        },
        "required": ["query"],
    },
)

CONTEXT_STORE_TOOL = Tool(
    name="context_store",
    description=(
        "Store a piece of knowledge in the OG context store. "
        "Text is embedded and stored with optional graph vertex creation."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The knowledge text to store (1-3 sentences)",
            },
            "chunk_type": {
                "type": "string",
                "enum": ["decision", "correction", "constraint", "pattern", "fact"],
                "description": "Type of knowledge chunk",
                "default": "fact",
            },
            "project_id": {
                "type": "string",
                "description": "Project identifier (default: 'default')",
                "default": "default",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Code entities or concepts mentioned",
                "default": [],
            },
            "session_id": {
                "type": "string",
                "description": "Source session identifier",
                "default": "",
            },
        },
        "required": ["text"],
    },
)

INSERT_CHUNK_SQL = """
INSERT INTO context_chunks (project_id, chunk_type, text, embedding, source_session, source_type)
VALUES ($1, $2, $3, $4::vector, $5, 'mcp')
ON CONFLICT (project_id, md5(text)) DO NOTHING
RETURNING id;
"""


class ContextMCPServer:
    """MCP server providing context_recall and context_store tools."""

    def __init__(self):
        self.pool = None
        self.embedder = None
        self.graph = None
        self.server = Server("og-context")
        self._setup_handlers()

    def _setup_handlers(self):
        @self.server.list_tools()
        async def list_tools():
            return [CONTEXT_RECALL_TOOL, CONTEXT_STORE_TOOL]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict):
            if name == "context_recall":
                return await self._recall(arguments)
            elif name == "context_store":
                return await self._store(arguments)
            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

    async def initialize(self):
        """Create database pool, embedder, and optional graph connection."""
        from dotenv import load_dotenv

        load_dotenv()

        from og.config.schema import Config

        config = Config()

        import asyncpg
        from pgvector.asyncpg import register_vector

        from og.memory.embeddings import EmbeddingClient

        self.pool = await asyncpg.create_pool(
            dsn=config.db.dsn,
            min_size=1,
            max_size=5,
            init=lambda conn: register_vector(conn),
        )
        self.embedder = EmbeddingClient(
            base_url=config.embedding.ollama_base_url,
            model=config.embedding.model,
        )
        # Quick connectivity check
        await self.embedder.embed("mcp init")
        logger.info("MCP server connected to PostgreSQL and embedding service")

        # Try to initialize knowledge graph
        try:
            from og.knowledge.graph import KnowledgeGraph

            self.graph = KnowledgeGraph(pool=self.pool, project_id="default")
            logger.info("Knowledge graph available for MCP queries")
        except Exception:
            logger.debug("Knowledge graph not available for MCP", exc_info=True)

    async def shutdown(self):
        """Close the database pool."""
        if self.pool is not None:
            await self.pool.close()

    async def _recall(self, args: dict) -> list[TextContent]:
        """Handle context_recall tool calls."""
        query = args.get("query", "")
        project_id = args.get("project_id", "default")
        entities = args.get("entities", [])
        limit = args.get("limit", 10)

        if not query:
            return [TextContent(type="text", text="Error: query is required")]

        try:
            from og.memory.pg import PgMemory

            graph = None
            if self.graph is not None:
                from og.knowledge.graph import KnowledgeGraph

                graph = KnowledgeGraph(pool=self.pool, project_id=project_id)

            memory = PgMemory(
                pool=self.pool,
                embedder=self.embedder,
                project_id=project_id,
                graph=graph,
            )
            results = await memory.search(query, limit=limit, entities=entities or None)

            if not results:
                return [TextContent(type="text", text="No results found.")]

            formatted = "\n\n---\n\n".join(results)
            return [TextContent(type="text", text=formatted)]
        except Exception as e:
            logger.warning("context_recall failed", exc_info=True)
            return [TextContent(type="text", text=f"Error: {e}")]

    async def _store(self, args: dict) -> list[TextContent]:
        """Handle context_store tool calls."""
        text = args.get("text", "")
        chunk_type = args.get("chunk_type", "fact")
        project_id = args.get("project_id", "default")
        entities = args.get("entities", [])
        session_id = args.get("session_id", "")

        if not text:
            return [TextContent(type="text", text="Error: text is required")]

        try:
            embedding = await self.embedder.embed(text)

            row = await self.pool.fetchrow(
                INSERT_CHUNK_SQL,
                project_id,
                chunk_type,
                text,
                embedding,
                session_id,
            )

            chunk_id = row["id"] if row else None
            if chunk_id is None:
                return [TextContent(type="text", text="Chunk already exists (deduplicated).")]

            # Create graph vertex if graph is available and entities are provided
            if self.graph is not None and entities:
                from og.knowledge.graph import KnowledgeGraph

                graph = KnowledgeGraph(pool=self.pool, project_id=project_id)
                vid = await graph.create_vertex(chunk_id, chunk_type, text, entities)
                if vid is not None and session_id:
                    await graph.link_to_session(vid, session_id)
                return [
                    TextContent(
                        type="text",
                        text=f"Stored chunk {chunk_id} with graph vertex {vid}.",
                    )
                ]

            return [TextContent(type="text", text=f"Stored chunk {chunk_id}.")]
        except Exception as e:
            logger.warning("context_store failed", exc_info=True)
            return [TextContent(type="text", text=f"Error: {e}")]


async def run_mcp_server():
    """Entry point: load config, initialize server, run stdio transport."""
    logging.basicConfig(level=logging.INFO)
    ctx = ContextMCPServer()
    try:
        await ctx.initialize()
        async with stdio_server() as (read_stream, write_stream):
            await ctx.server.run(
                read_stream, write_stream, ctx.server.create_initialization_options()
            )
    finally:
        await ctx.shutdown()


def main():
    """Synchronous entry point for the og-mcp console script."""
    asyncio.run(run_mcp_server())


if __name__ == "__main__":
    main()
