# backend/services/rag.py
"""
Lehký RAG wrapper.
- Pokud existuje FAISS index (data/faiss.index + data/store.npy), použije se.
- Když neexistuje, search() vrátí prázdný list a systém běží dál bez RAG.
Index vytvoříš skriptem (např. scripts/build_rag.py).
"""

import os
from typing import List, Tuple
import numpy as np

try:
    import faiss  # type: ignore
except Exception:
    faiss = None  # povolí běh i bez faiss

from openai import OpenAI

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INDEX_PATH = os.getenv("RAG_INDEX_PATH", os.path.join(ROOT, "data", "faiss.index"))
STORE_PATH = os.getenv("RAG_STORE_PATH", os.path.join(ROOT, "data", "store.npy"))

class RagStore:
    def __init__(self, client: OpenAI):
        self.client = client
        self.index = None
        self.texts: List[str] = []

    def load(self) -> bool:
        if faiss is None:
            return False
        if not (os.path.exists(INDEX_PATH) and os.path.exists(STORE_PATH)):
            return False
        try:
            self.index = faiss.read_index(INDEX_PATH)
            self.texts = np.load(STORE_PATH, allow_pickle=True).tolist()
            return True
        except Exception:
            self.index = None
            self.texts = []
            return False

    def _embed(self, texts: List[str]) -> np.ndarray:
        vecs = self.client.embeddings.create(model=EMBED_MODEL, input=texts)
        arr = np.array([d.embedding for d in vecs.data], dtype="float32")
        return arr

    def search(self, query: str, k: int = 4) -> List[Tuple[str, float]]:
        if faiss is None or self.index is None or not self.texts:
            return []
        q = self._embed([query]).astype("float32")
        # kosinová podobnost (normalizace L2)
        faiss.normalize_L2(q)
        D, I = self.index.search(q, k)
        out: List[Tuple[str, float]] = []
        for idx, score in zip(I[0], D[0]):
            if idx == -1:
                continue
            out.append((self.texts[idx], float(score)))
        return out
