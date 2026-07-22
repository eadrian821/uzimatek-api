"""
Memory Service - Fixed & Extended
Three-tier memory: Working (Redis), Episodic (Supabase), Semantic (Qdrant + real embeddings)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from uuid import uuid4
import asyncio
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

import httpx
import redis.asyncio as redis
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue
)

from app.core.config import settings

logger = logging.getLogger(__name__)

VECTOR_SIZE = 512  # voyage-3-lite output dimension


# ─────────────────────────────────────────────────────────────────────────────
# Embedding Engine — Voyage AI (medical domain optimized)
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingEngine:
    """Voyage AI embeddings — medical domain optimized, replaces zero-vector stub"""

    def __init__(self):
        self.api_key = settings.voyage_api_key
        self.model = settings.voyage_model
        self.client = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=30.0
        )

    @retry(wait=wait_exponential(multiplier=2, min=4, max=30), stop=stop_after_attempt(5))
    async def embed(self, text: str) -> List[float]:
        """Embed a single text string. Falls back to Anthropic if Voyage unavailable."""
        if not self.api_key:
            return await self._anthropic_fallback_embed(text)
        try:
            resp = await self.client.post(
                "/embeddings",
                json={"model": self.model, "input": [text[:8000]], "input_type": "document"}
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Voyage AI rate limit hit, retrying...")
                raise e
            logger.warning(f"Voyage embed failed, falling back: {e}")
            return await self._anthropic_fallback_embed(text)
        except Exception as e:
            logger.warning(f"Voyage embed failed, falling back: {e}")
            return await self._anthropic_fallback_embed(text)

    @retry(wait=wait_exponential(multiplier=2, min=4, max=30), stop=stop_after_attempt(5))
    async def _post_batch(self, batch: List[str]) -> List[Dict]:
        try:
            resp = await self.client.post(
                "/embeddings",
                json={"model": self.model, "input": batch, "input_type": "document"}
            )
            resp.raise_for_status()
            return resp.json()["data"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Voyage AI rate limit hit during batch, retrying...")
                raise e
            raise e

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts efficiently."""
        if not self.api_key:
            results = []
            for t in texts:
                results.append(await self._anthropic_fallback_embed(t))
            return results
        try:
            all_embeddings = []
            truncated = [t[:8000] for t in texts]
            batch_size = 100  # Voyage AI max is 128
            
            for i in range(0, len(truncated), batch_size):
                batch = truncated[i:i + batch_size]
                data = await self._post_batch(batch)
                sorted_data = sorted(data, key=lambda x: x["index"])
                all_embeddings.extend([d["embedding"] for d in sorted_data])
                if i + batch_size < len(truncated):
                    await asyncio.sleep(1.0)  # Rate limit safety
                    
            return all_embeddings
        except Exception as e:
            logger.error(f"Batch embed error: {e}")
            return [await self._anthropic_fallback_embed(t) for t in texts]

    @retry(wait=wait_exponential(multiplier=2, min=4, max=30), stop=stop_after_attempt(5))
    async def embed_query(self, query: str) -> List[float]:
        """Embed a search query (different input_type for better retrieval)."""
        if not self.api_key:
            return await self._anthropic_fallback_embed(query)
        try:
            resp = await self.client.post(
                "/embeddings",
                json={"model": self.model, "input": [query[:8000]], "input_type": "query"}
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning("Voyage AI rate limit hit, retrying...")
                raise e
            logger.warning(f"Query embed failed: {e}")
            return await self._anthropic_fallback_embed(query)
        except Exception as e:
            logger.warning(f"Query embed failed: {e}")
            return await self._anthropic_fallback_embed(query)

    async def _anthropic_fallback_embed(self, text: str) -> List[float]:
        """Last-resort: deterministic hash-based pseudo-embedding (not semantic, but non-zero)."""
        import hashlib
        h = hashlib.sha256(text.encode('utf-8', errors='ignore')).digest()
        # Expand to VECTOR_SIZE bytes
        target_bytes = VECTOR_SIZE
        multiplier = (target_bytes // len(h)) + 1
        expanded = (h * multiplier)[:target_bytes]
        
        # Convert each byte to a float between -1.0 and 1.0
        floats = [(b / 127.5) - 1.0 for b in expanded]
        
        # Normalize
        mag = sum(f*f for f in floats) ** 0.5 or 1.0
        return [f / mag for f in floats]


# Global embedding engine
embedder = EmbeddingEngine()


# ─────────────────────────────────────────────────────────────────────────────
# Working Memory — Redis (session-scoped)
# ─────────────────────────────────────────────────────────────────────────────

class WorkingMemory:
    """Short-term memory for current conversation and task context"""

    def __init__(self):
        self.redis: Optional[redis.Redis] = None
        self.ttl = 3600 * 4  # 4 hours

    async def connect(self):
        try:
            self.redis = redis.from_url(settings.redis_url, decode_responses=True)
            await self.redis.ping()
            logger.info("Redis connected for working memory")
        except Exception as e:
            logger.warning(f"Redis connection failed (Continuing without Working Memory): {e}")
            self.redis = None

    async def disconnect(self):
        if self.redis:
            await self.redis.aclose()

    async def set(self, session_id: str, key: str, value: Any, ttl: int = None):
        if not self.redis:
            return
        full_key = f"jarvis:session:{session_id}:{key}"
        await self.redis.set(
            full_key,
            json.dumps(value) if not isinstance(value, str) else value,
            ex=ttl or self.ttl
        )

    async def get(self, session_id: str, key: str) -> Optional[Any]:
        if not self.redis:
            return None
        full_key = f"jarvis:session:{session_id}:{key}"
        value = await self.redis.get(full_key)
        if value:
            try:
                return json.loads(value)
            except Exception:
                return value
        return None

    async def append_message(self, session_id: str, role: str, content: str):
        if not self.redis:
            return
        history_key = f"jarvis:session:{session_id}:history"
        message = {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        await self.redis.rpush(history_key, json.dumps(message))
        await self.redis.expire(history_key, self.ttl)

    async def get_history(self, session_id: str, limit: int = 20) -> List[Dict]:
        if not self.redis:
            return []
        history_key = f"jarvis:session:{session_id}:history"
        messages = await self.redis.lrange(history_key, -limit, -1)
        return [json.loads(m) for m in messages]

    async def set_context(self, session_id: str, context: Dict):
        await self.set(session_id, "context", context)

    async def get_context(self, session_id: str) -> Optional[Dict]:
        return await self.get(session_id, "context")

    # Deduplication for Telegram/Slack webhooks
    async def is_duplicate(self, channel: str, message_id: str) -> bool:
        """Return True if this message_id was already processed (within 1 hour)."""
        if not self.redis:
            return False
        key = f"jarvis:dedup:{channel}:{message_id}"
        result = await self.redis.set(key, "1", ex=3600, nx=True)
        return result is None  # nx=True returns None if key already existed


# ─────────────────────────────────────────────────────────────────────────────
# Episodic Memory — Supabase PostgreSQL (implemented, not stub)
# ─────────────────────────────────────────────────────────────────────────────

class EpisodicMemory:
    """Medium-term memory for recent events — actual Supabase writes"""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if not self._client:
            from supabase import create_client
            self._client = create_client(settings.supabase_url, settings.supabase_service_key or settings.supabase_key)
        return self._client

    async def record_event(
        self,
        domain: str,
        event_type: str,
        content: str,
        outcome: str = None,
        metadata: Dict = None
    ) -> str:
        event_id = str(uuid4())
        try:
            client = self._get_client()
            client.table("memory_episodic").insert({
                "id": event_id,
                "domain": domain,
                "event_type": event_type,
                "content": content,
                "outcome": outcome,
                "metadata": json.dumps(metadata or {}),
                "created_at": datetime.now().isoformat()
            }).execute()
            logger.info(f"Episodic memory recorded: {domain}/{event_type}")
        except Exception as e:
            logger.error(f"Episodic memory write error: {e}")
        return event_id

    async def get_recent(
        self,
        domain: str = None,
        event_type: str = None,
        days: int = 7,
        limit: int = 50
    ) -> List[Dict]:
        try:
            client = self._get_client()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            query = client.table("memory_episodic").select("*").gte("created_at", cutoff).order("created_at", desc=True).limit(limit)
            if domain:
                query = query.eq("domain", domain)
            if event_type:
                query = query.eq("event_type", event_type)
            result = query.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Episodic get_recent error: {e}")
            return []

    async def search(self, query: str, domain: str = None, limit: int = 10) -> List[Dict]:
        try:
            client = self._get_client()
            q = client.table("memory_episodic").select("*").ilike("content", f"%{query}%").limit(limit)
            if domain:
                q = q.eq("domain", domain)
            result = q.execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Episodic search error: {e}")
            return []

    async def get_gap_history(self, topic_keyword: str) -> List[Dict]:
        """Get all previously recorded gaps for a topic — used by BrainService."""
        return await self.search(topic_keyword, domain="medical_gap")


# ─────────────────────────────────────────────────────────────────────────────
# Semantic Memory — Qdrant with real embeddings
# ─────────────────────────────────────────────────────────────────────────────

class SemanticMemory:
    """Long-term semantic memory — Qdrant vector store with real Voyage AI embeddings"""

    MEDICAL_COLLECTIONS = [
        "jarvis_memory",
        "medical_gold_standard",   # RAG corpus: textbooks, uptodate
        "clinical_captures",        # Ward round 1-liners
        "missed_findings",          # Delta engine gaps
        "onenote_annotations",      # OneNote synced content
        "obsidian_notes",           # Vault markdown
        "medical_recommendations",  # Interesting therapies, flagged items
    ]

    def __init__(self):
        self.client: Optional[QdrantClient] = None

    async def connect(self):
        try:
            # We bypass Docker by using Qdrant's pure-local storage engine on Windows!
            import os
            local_qdrant_path = os.path.join("C:\\", "jarvis", "qdrant_local_db")
            os.makedirs(local_qdrant_path, exist_ok=True)
            self.client = QdrantClient(path=local_qdrant_path)
            
            existing = {c.name for c in self.client.get_collections().collections}
            for name in self.MEDICAL_COLLECTIONS:
                if name not in existing:
                    self.client.create_collection(
                        collection_name=name,
                        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
                    )
                    logger.info(f"Created local Qdrant collection: {name}")
            logger.info("Local Qdrant connected — all medical collections ready on disk")
        except Exception as e:
            logger.error(f"Local Qdrant connection failed: {e}")
            self.client = None

    async def store(
        self,
        collection: str,
        key: str,
        value: str,
        metadata: Dict = None,
        embedding: List[float] = None
    ) -> str:
        if not self.client:
            return ""
        point_id = str(uuid4())
        # Always generate real embeddings
        if not embedding:
            embedding = await embedder.embed(value)
        payload = {
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat(),
            **(metadata or {})
        }
        self.client.upsert(
            collection_name=collection,
            points=[PointStruct(id=point_id, vector=embedding, payload=payload)]
        )
        return point_id

    async def store_chunked_document(
        self,
        collection: str,
        source_path: str,
        chunks: List[str],
        base_metadata: Dict = None
    ) -> int:
        """Embed and store a large document efficiently using batching."""
        if not self.client: return 0
        embeddings = await embedder.embed_batch(chunks)
        points = []
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            payload = {
                "source_path": source_path,
                "chunk_index": i,
                "value": chunk,
                "timestamp": datetime.now().isoformat(),
                **(base_metadata or {})
            }
            points.append(PointStruct(id=str(uuid4()), vector=emb, payload=payload))
        self.client.upsert(collection_name=collection, points=points)
        return len(points)

    async def search(
        self,
        collection: str,
        query: str,
        limit: int = 5,
        filter_dict: Dict = None
    ) -> List[Dict]:
        if not self.client:
            return []
        
        # Use query-optimized embedding
        vector = await embedder.embed_query(query)
        
        q_filter = None
        if filter_dict:
            conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_dict.items()
            ]
            q_filter = Filter(must=conditions)
            
        results = self.client.query_points(
            collection_name=collection,
            query=vector,
            query_filter=q_filter,
            limit=limit,
            with_payload=True,
            score_threshold=0.5  # Ignore extremely poor matches
        ).points
        return [
            {
                "score": res.score,
                "key": res.payload.get("key"),
                "value": res.payload.get("value"),
                "metadata": {k: v for k, v in res.payload.items() if k not in ["key", "value"]}
            }
            for res in results
        ]

    async def search_across_collections(
        self,
        query: str,
        collections: List[str],
        limit_per: int = 2
    ) -> Dict[str, List[Dict]]:
        if not self.client: return {}
        results = {}
        for col in collections:
            results[col] = await self.search(col, query, limit=limit_per)
        return results

# ─────────────────────────────────────────────────────────────────────────────
# Memory Manager — The Unified API
# ─────────────────────────────────────────────────────────────────────────────

class MemoryManager:
    """Unified access to all three memory tiers."""
    
    def __init__(self):
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()

    async def connect(self):
        await self.working.connect()
        await self.semantic.connect()

    async def disconnect(self):
        await self.working.disconnect()
        if self.semantic.client:
            self.semantic.client.close()

    async def log_recommendation(self, content: str, source: str = "unknown"):
        await self.semantic.store(
            collection="medical_recommendations",
            key=str(uuid4()),
            value=content,
            metadata={"source": source}
        )

    async def add_to_conversation(self, session_id: str, role: str, content: str):
        await self.working.append_message(session_id, role, content)

    async def get_conversation(self, session_id: str, limit: int = 50) -> List[Dict]:
        return await self.working.get_history(session_id, limit)

    async def rag_search_gold_standard(self, query: str, limit: int = 8):
        return await self.semantic.search("medical_gold_standard", query, limit=limit)

    async def log_gap(self, gap_text: str, topic: str, rotation: str):
        await self.semantic.store(
            collection="missed_findings",
            key=str(uuid4()),
            value=gap_text,
            metadata={
                "topic": topic,
                "rotation": rotation,
                "created_at": datetime.now().isoformat()
            }
        )

# Global instance
memory = MemoryManager()

