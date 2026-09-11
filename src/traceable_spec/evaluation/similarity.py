"""Optional local multilingual semantic similarity for benchmark slot matching."""

from __future__ import annotations

import importlib
from typing import Any


class MultilingualSentenceSimilarity:
    """Cosine similarity using a local Sentence Transformers model.

    The model is loaded lazily and every unique string embedding is cached for
    one evaluator process. No text is sent to an external API.
    """

    name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, *, local_files_only: bool = False) -> None:
        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
        except ImportError as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError(
                "Install the evaluation extra: poetry install --with evaluation"
            ) from exc
        self._model: Any = sentence_transformers.SentenceTransformer(
            self.name,
            local_files_only=local_files_only,
        )
        self._cache: dict[str, Any] = {}

    def _embedding(self, text: str) -> Any:
        normalized = " ".join(text.casefold().split())
        if normalized not in self._cache:
            self._cache[normalized] = self._model.encode(
                normalized,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return self._cache[normalized]

    def __call__(self, left: str, right: str) -> float:
        if not left.strip() or not right.strip():
            return 0.0
        left_embedding = self._embedding(left)
        right_embedding = self._embedding(right)
        return float(left_embedding @ right_embedding)
