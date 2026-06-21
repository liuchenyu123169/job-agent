import os

from app.rag.loader import load_knowledge_files
from app.rag.splitter import split_documents
from app.rag.vector_store import ChromaKnowledgeStore

# ChromaDB client 单例（避免每次 search 重建 PersistentClient）
_store: ChromaKnowledgeStore | None = None


def get_store() -> ChromaKnowledgeStore:
    global _store
    if _store is None:
        _store = ChromaKnowledgeStore()
    return _store


def build_knowledge_base() -> dict:
    knowledge_dir = os.getenv("KNOWLEDGE_DIR", "data/knowledge")
    documents = load_knowledge_files(knowledge_dir)
    if not documents:
        return {"file_count": 0, "chunk_count": 0}

    chunks = split_documents(documents)
    if not chunks:
        return {"file_count": len(documents), "chunk_count": 0}

    store = ChromaKnowledgeStore()
    chunk_count = store.rebuild(chunks)
    return {"file_count": len(documents), "chunk_count": chunk_count}


def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    return get_store().search(query=query, top_k=top_k)
