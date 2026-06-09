from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OpenAIEmbeddingClient:
    base_url: str
    model: str
    timeout_seconds: int = 60

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError("requests is required for OpenAI-compatible embeddings") from exc

        response = requests.post(
            f"{self.base_url.rstrip('/')}/embeddings",
            json={"model": self.model, "input": texts},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]
