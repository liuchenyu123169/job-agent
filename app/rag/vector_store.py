import os
import re
import uuid

import chromadb

from app.rag.embedding import EmbeddingClient
from app.rag.splitter import MIN_CHUNK_CONTENT_LENGTH


class ChromaKnowledgeStore:
    def __init__(self) -> None:
        chroma_dir = os.getenv("CHROMA_DIR", "data/chroma")
        collection_name = os.getenv("CHROMA_COLLECTION_NAME", "job_agent_knowledge")

        self.client = chromadb.PersistentClient(path=chroma_dir)
        self.collection_name = collection_name
        self._embedding_client: EmbeddingClient | None = None

    @property
    def embedding_client(self) -> EmbeddingClient:
        if self._embedding_client is None:
            self._embedding_client = EmbeddingClient()
        return self._embedding_client

    def rebuild(self, chunks: list[dict]) -> int:
        try:
            self.client.delete_collection(name=self.collection_name)
        except Exception:
            pass

        if not chunks:
            return 0

        collection = self.client.create_collection(name=self.collection_name)
        contents = [chunk["content"] for chunk in chunks]
        embeddings = self.embedding_client.embed_texts(contents)

        if not embeddings:
            return 0

        collection.add(
            ids=[str(uuid.uuid4()) for _ in chunks],
            documents=contents,
            embeddings=embeddings,
            metadatas=[
                {
                    "source": chunk.get("source"),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "title": chunk.get("title", ""),
                    "section_path": chunk.get("section_path", ""),
                }
                for chunk in chunks
            ],
        )
        return len(chunks)

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        collection = self._get_collection()
        if collection is None:
            return []
        if self._is_collection_empty(collection):
            return []

        query_embedding = self.embedding_client.embed_query(query)
        if not query_embedding:
            return []

        candidate_k = min(max(top_k * 4, top_k), 50)
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=candidate_k,
        )

        documents = results.get("documents", [[]])
        metadatas = results.get("metadatas", [[]])
        distances = results.get("distances", [[]])

        items: list[dict] = []
        for content, metadata, score in zip(
            documents[0] if documents else [],
            metadatas[0] if metadatas else [],
            distances[0] if distances else [],
        ):
            if not content or len(content.strip()) < MIN_CHUNK_CONTENT_LENGTH:
                continue
            items.append(
                {
                    "content": content,
                    "source": metadata.get("source") if metadata else None,
                    "score": float(score) if score is not None else None,
                    "title": metadata.get("title") if metadata else "",
                    "section_path": metadata.get("section_path") if metadata else "",
                }
            )

        reranked = sorted(
            items,
            key=lambda item: (
                -_keyword_boost(query, item),
                item["score"] if item["score"] is not None else float("inf"),
                len(item["content"]),
            ),
        )
        return [
            {
                "content": item["content"],
                "source": item["source"],
                "score": item["score"],
                "title": item["title"],
                "section_path": item["section_path"],
            }
            for item in reranked[:top_k]
        ]

    def _get_collection(self):
        try:
            return self.client.get_collection(name=self.collection_name)
        except Exception:
            return None

    @staticmethod
    def _is_collection_empty(collection) -> bool:
        try:
            return collection.count() == 0
        except Exception:
            return True


def _keyword_boost(query: str, item: dict) -> int:
    normalized_query = _normalize_text(query)
    title = _normalize_text(item.get("title", ""))
    section_path = _normalize_text(item.get("section_path", ""))
    content = _normalize_text(item.get("content", ""))

    boost = 0
    if normalized_query and normalized_query in title:
        boost += 6
    if normalized_query and normalized_query in section_path:
        boost += 4
    if normalized_query and normalized_query in content:
        boost += 2

    for token in _query_tokens(query):
        if token and token in title:
            boost += 3
        if token and token in section_path:
            boost += 2
        if token and token in content:
            boost += 1
    return boost


def _query_tokens(query: str) -> list[str]:
    text = _normalize_text(query)
    tokens = [
        token
        for token in re.split(r"[\s,:\uff1a\uff0c\u3002\uff01\uff1f!?\u3001]+", text)
        if token
    ]
    if not tokens and text:
        tokens = [text]
    return tokens


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())
