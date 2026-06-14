import os

from openai import OpenAI


EMBEDDING_BATCH_SIZE = 64


class EmbeddingClient:
    def __init__(self) -> None:
        api_key = os.getenv("ZHIPU_API_KEY")
        if not api_key:
            raise RuntimeError("ZHIPU_API_KEY is not configured")

        base_url = os.getenv("ZHIPU_BASE_URL")
        if not base_url:
            raise RuntimeError("ZHIPU_BASE_URL is not configured")

        model = os.getenv("EMBEDDING_MODEL")
        if not model:
            raise RuntimeError("EMBEDDING_MODEL is not configured")

        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean_texts = [text for text in texts if text and text.strip()]
        if not clean_texts:
            return []

        embeddings: list[list[float]] = []
        for index in range(0, len(clean_texts), EMBEDDING_BATCH_SIZE):
            batch = clean_texts[index : index + EMBEDDING_BATCH_SIZE]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            embeddings.extend(item.embedding for item in response.data)

        return embeddings

    def embed_query(self, query: str) -> list[float]:
        if not query or not query.strip():
            raise RuntimeError("query must not be empty")

        response = self.client.embeddings.create(
            model=self.model,
            input=query.strip(),
        )
        return response.data[0].embedding if response.data else []
