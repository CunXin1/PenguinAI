"""
Metadata-filtered RAG retriever.
Queries pgvector for ticker-specific posts within a recency window.
No cross-ticker contamination — ticker + timestamp filter is hardcoded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.rag.embedder import embedder


class RAGRetriever:
    def __init__(self, db_session_factory=None):
        self._session_factory = db_session_factory

    async def retrieve(
        self,
        ticker: str,
        query_text: str | None = None,
        top_k: int = 5,
        hours: int = 72,
        db: AsyncSession | None = None,
    ) -> list[str]:
        """
        Retrieve top_k relevant post snippets for a ticker within the past N hours.
        Uses cosine similarity on pgvector embeddings with metadata filter.
        """
        if db is None:
            return []

        since = datetime.now(UTC) - timedelta(hours=hours)

        # If no query text, use ticker as the query
        query = query_text or f"{ticker} stock investment analysis"
        query_embedding = embedder.encode(query)

        rows = await db.execute(
            text("""
                SELECT content, finbert_score,
                       1 - (embedding <=> :embedding::vector) AS similarity
                FROM social_posts
                WHERE ticker = :ticker
                  AND time >= :since
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top_k
            """),
            {
                "ticker": ticker,
                "since": since,
                "embedding": f"[{','.join(str(x) for x in query_embedding.tolist())}]",
                "top_k": top_k,
            },
        )
        results = rows.mappings().all()
        return [row["content"][:280] for row in results]  # truncate to tweet length


rag_retriever = RAGRetriever()
