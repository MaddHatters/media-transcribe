from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Document:
    id: str
    text: str
    metadata: dict


@dataclass
class SearchResult:
    document: Document
    score: float


class VectorStore(Protocol):
    async def index(self, documents: list[Document]) -> int: ...
    async def search(self, query: str, top_k: int = 10) -> list[SearchResult]: ...
    async def delete(self, doc_ids: list[str]) -> int: ...
