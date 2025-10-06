# scripts/build_rag.py
"""
Rebuild FAISS RAG index (semantic search) pro Edmunda.

Použití:
  python scripts/build_rag.py \
      --out-index data/faiss.index \
      --out-store data/store.npy \
      backend/caps/CAPABILITIES.md docs/**/*.md

Poznámky:
- Vektory normalizujeme (L2) a použijeme IndexFlatIP -> kosinová podobnost.
- Texty ukládáme do numpy souboru (list[str]) -> kompatibilní s RagStore.
"""

import os
import sys
import glob
import argparse
from pathlib import Path

import numpy as np

try:
    import faiss  # type: ignore
except Exception as e:
    print("FAISS není nainstalováno. Nainstaluj např.: pip install faiss-cpu")
    sys.exit(1)

from openai import OpenAI


# ====== Konfigurace ======
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "text-embedding-3-small")


def load_files(patterns: list[str]) -> list[tuple[str, str]]:
    """Načte soubory dle patternů (glob), vrátí [(path, text), ...]."""
    paths: list[str] = []
    for p in patterns:
        paths.extend(glob.glob(p, recursive=True))

    out: list[tuple[str, str]] = []
    for p in sorted(set(paths)):
        fp = Path(p)
        if not fp.is_file():
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        text = text.strip()
        if text:
            out.append((str(fp), text))
    return out


def chunk_text(text: str, max_chars: int = 1800, overlap: int = 200) -> list[str]:
    """
    Jednoduchý chunker podle znaků (bez rozbíjení slovníků).
    max_chars ~ 1800 je bezpečné pro embedding; overlap drží kontext.
    """
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(i + max_chars, n)
        chunk = text[i:j]
        chunks.append(chunk)
        if j >= n:
            break
        i = j - overlap
        if i < 0:
            i = 0
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-index", default="data/faiss.index")
    ap.add_argument("--out-store", default="data/store.npy")
    ap.add_argument("inputs", nargs="+", help="Seznam souborů nebo glob patternů")
    args = ap.parse_args()

    # 1) Načti soubory (včetně CAPABILITIES.md)
    pairs = load_files(args.inputs)
    if not pairs:
        print("Nenalezeny žádné soubory pro indexaci.")
        sys.exit(2)

    # 2) Chunkuj a připrav texty
    texts: list[str] = []
    meta: list[str] = []  # (volitelně můžeme uchovat path v každém chunku)
    for path, txt in pairs:
        chunks = chunk_text(txt)
        for ch in chunks:
            # Doplníme prefix se jménem souboru -> lepší interpretace při citování
            # (Pokud to v produkci nechceš, klidně vypni.)
            texts.append(f"[{Path(path).name}]\n{ch}")
            meta.append(path)

    print(f"Indexuji {len(texts)} textových chunků z {len(pairs)} souborů.")
    if len(texts) == 0:
        print("Prázdné texty, končím.")
        sys.exit(3)

    # 3) Vytvoř embeddingy
    client = OpenAI()
    # OpenAI API umí vzít batch -> rozdělíme po 100
    vecs = []
    batch = 100
    for i in range(0, len(texts), batch):
        sub = texts[i:i+batch]
        resp = client.embeddings.create(model=EMBED_MODEL, input=sub)
        vecs.extend([d.embedding for d in resp.data])

    X = np.array(vecs, dtype="float32")
    # normalizace L2 (kosinová podobnost s IP indexem)
    faiss.normalize_L2(X)

    # 4) FAISS index
    idx = faiss.IndexFlatIP(X.shape[1])
    idx.add(X)

    # 5) Ulož výsledky
    out_index = Path(args.out_index)
    out_store = Path(args.out_store)
    out_index.parent.mkdir(parents=True, exist_ok=True)
    out_store.parent.mkdir(parents=True, exist_ok=True)

    faiss.write_index(idx, str(out_index))
    # texts ukládáme jako numpy objektové pole -> kompatibilní s RagStore (list[str])
    np.save(str(out_store), np.array(texts, dtype=object))

    print(f"OK → {out_index} + {out_store}")
    print(f"Model: {EMBED_MODEL}")


if __name__ == "__main__":
    main()
