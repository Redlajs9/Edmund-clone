# backend/api/routers/logic.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import os, sqlite3
import numpy as np

# --- FAISS ---
try:
    import faiss
except Exception:
    faiss = None

# --- OpenAI: nový klient ---
try:
    from openai import OpenAI
    _client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except Exception as e:
    _client = None

# --- Cesty (z .env s fallbackem) ---
SQLITE = os.getenv("IO_DB_PATH", "/app/data/io.db")
FAISS_VEC_PATH = os.getenv("RAG_HWF_INDEX_PATH", "/app/data/faiss_hwf.index")
FAISS_STORE_PATH = os.getenv("RAG_HWF_STORE_PATH", "/app/data/hwf_store.npy")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMB_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-large")

router = APIRouter(prefix="/logic", tags=["logic"])


class AskReq(BaseModel):
    question: str
    top_k: int = 5


def embed_one(q: str) -> np.ndarray:
    if _client is None:
        raise HTTPException(500, "OpenAI klient není inicializovaný (chybí OPENAI_API_KEY?).")
    res = _client.embeddings.create(model=EMB_MODEL, input=[q])
    x = np.array(res.data[0].embedding, dtype=np.float32)[None, :]
    if faiss is None:
        return x
    faiss.normalize_L2(x)  # cosine
    return x


def fetch_fb_texts(ids):
    if not ids:
        return []
    con = sqlite3.connect(SQLITE)
    cur = con.cursor()
    q = f"SELECT id,name,body FROM fb_blocks WHERE id IN ({','.join('?'*len(ids))})"
    rows = cur.execute(q, ids).fetchall()
    con.close()
    mp = {rid: (name, body) for (rid, name, body) in rows}
    return [(rid, mp[rid][0], mp[rid][1]) for rid in ids if rid in mp]


@router.get("/ping")
def ping():
    return {"status": "ok"}


@router.post("/ask")
def ask(req: AskReq):
    if faiss is None:
        raise HTTPException(500, "FAISS není nainstalován v API kontejneru.")
    if _client is None:
        raise HTTPException(500, "OpenAI klient není inicializovaný (OPENAI_API_KEY?).")
    if not (os.path.exists(FAISS_VEC_PATH) and os.path.exists(FAISS_STORE_PATH)):
        raise HTTPException(400, "Nejdřív spusť ingest HWF (backend/ingest_hwf.py).")

    # načti index a mapování ID
    index = faiss.read_index(FAISS_VEC_PATH)
    fb_ids = np.load(FAISS_STORE_PATH)
    ntotal = index.ntotal
    if ntotal == 0:
        raise HTTPException(400, "HWF index je prázdný. Zkus znovu spustit ingest.")

    # dotaz → embedding → vyhledání
    qv = embed_one(req.question)
    k = max(1, min(req.top_k, ntotal))
    D, I = index.search(qv, k)
    hit_ids = [int(fb_ids[i]) for i in I[0] if i >= 0]

    hits = fetch_fb_texts(hit_ids)
    if not hits:
        # fallback – vrať aspoň vysvětlení, že nic nenašel
        return {
            "answer": "Nenalezl jsem relevantní FB v indexu. Zkontroluj, že ingest načetl kód/NETWORKS z XML exportů.",
            "used_blocks": []
        }

    # slož kontext
    context = "\n\n".join([f"=== {name} (ID {rid}) ===\n{body}" for rid, name, body in hits])

    prompt = f"""Jsi PLC/TIA odborník. Odpověz česky, stručně a přesně.
Dotaz: {req.question}

Kontext (výřezy z FB bloků):
{context}

Instrukce:
- Pokud něco není v kontextu jisté, uveď co chybí (FB, parametr, síť).
- Uveď, které FB jsi použil (názvy)."""

    chat = _client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )
    answer = chat.choices[0].message.content
    used = [name for _, name, _ in hits]
    return {"answer": answer, "used_blocks": used}
