"""Knowledge base service wrapping HelloAgents RAGTool."""

from __future__ import annotations

import logging
from typing import Any, Optional

from config import Configuration

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """Wraps RAGTool to provide document upload, search, and management."""

    def __init__(self, config: Configuration):
        self.config = config
        self.rag_tool = None

        if not config.enable_rag:
            logger.info("RAG knowledge base is disabled")
            return

        try:
            from hello_agents.tools.builtin.rag_tool import RAGTool

            self.rag_tool = RAGTool(
                knowledge_base_path=config.rag_knowledge_base_path,
                qdrant_url=config.qdrant_url,
                qdrant_api_key=config.qdrant_api_key,
                collection_name=config.rag_collection_name,
                rag_namespace=config.rag_namespace,
            )
            logger.info(
                "RAG knowledge base initialized: collection=%s path=%s",
                config.rag_collection_name,
                config.rag_knowledge_base_path,
            )
        except ImportError:
            logger.warning(
                "RAGTool dependencies not installed (qdrant-client, markitdown). "
                "Knowledge base features will be unavailable."
            )
        except Exception as exc:
            logger.exception("Failed to initialize RAGTool: %s", exc)

    @property
    def available(self) -> bool:
        return self.rag_tool is not None

    def upload_document(self, file_path: str) -> dict[str, Any]:
        """Add a document to the knowledge base via RAGTool's add_document action."""
        if not self.available:
            return {"status": "error", "message": "Knowledge base is not available"}

        try:
            result = self.rag_tool.run({
                "input": file_path,
                "action": "add_document",
            })
            logger.info("Document uploaded to KB: %s", file_path)
            return {"status": "ok", "result": str(result)}
        except Exception as exc:
            logger.exception("Failed to upload document: %s", exc)
            return {"status": "error", "message": str(exc)}

    def add_text(self, text: str, metadata: Optional[dict] = None) -> dict[str, Any]:
        """Add raw text to the knowledge base."""
        if not self.available:
            return {"status": "error", "message": "Knowledge base is not available"}

        try:
            result = self.rag_tool.run({
                "input": text,
                "action": "add_text",
            })
            logger.info("Text added to KB (length=%d)", len(text))
            return {"status": "ok", "result": str(result)}
        except Exception as exc:
            logger.exception("Failed to add text: %s", exc)
            return {"status": "error", "message": str(exc)}

    def search(self, query: str, top_k: int = 3) -> str:
        """Search the knowledge base and return formatted context."""
        if not self.available:
            return ""

        try:
            result = self.rag_tool.run({
                "input": query,
                "action": "search",
            })
            if isinstance(result, str):
                return result
            return str(result)
        except Exception as exc:
            logger.warning("KB search failed for query '%s': %s", query, exc)
            return ""

    def stats(self) -> dict[str, Any]:
        """Get knowledge base statistics."""
        if not self.available:
            return {"status": "unavailable", "message": "Knowledge base is not available"}

        try:
            result = self.rag_tool.run({
                "input": "stats",
                "action": "stats",
            })
            return {"status": "ok", "result": str(result)}
        except Exception as exc:
            logger.exception("Failed to get KB stats: %s", exc)
            return {"status": "error", "message": str(exc)}

    def clear(self) -> dict[str, Any]:
        """Clear all entries in the knowledge base."""
        if not self.available:
            return {"status": "unavailable", "message": "Knowledge base is not available"}

        try:
            result = self.rag_tool.run({
                "input": "clear",
                "action": "clear",
            })
            logger.info("Knowledge base cleared")
            return {"status": "ok", "result": str(result)}
        except Exception as exc:
            logger.exception("Failed to clear KB: %s", exc)
            return {"status": "error", "message": str(exc)}
