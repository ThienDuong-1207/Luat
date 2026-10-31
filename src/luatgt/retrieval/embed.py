"""Sinh embedding (spec 3.1: BAAI/bge-m3, dim 1024). Nạp model lúc dùng để import nhẹ."""

from __future__ import annotations

from typing import Protocol

from luatgt.common.config import Settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbedder:
    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import SentenceTransformer

        cfg = settings.embedding
        self.batch_size = cfg.batch_size
        self.model = SentenceTransformer(cfg.model)
        self.model.max_seq_length = cfg.max_seq_length

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                    show_progress_bar=len(texts) > self.batch_size)
        return [v.tolist() for v in vectors]


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
