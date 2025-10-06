# backend/api/routers/pids.py
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from backend.rag.pid_rag import PIDRAG
import os, re

router = APIRouter(prefix="/pids", tags=["pids"])
rag = PIDRAG()

# ----- Konfigurace cesty s PDF PID výkresy -----
PID_DATA_DIR = os.getenv("PID_DATA_DIR", "/app/data/pids")
ALLOWED_EXTS = {".pdf"}

# =======================
#       MODELY
# =======================
class SearchBody(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 5

class TagBody(BaseModel):
    tag: str = Field(..., min_length=1)

class ReindexBody(BaseModel):
    force_ocr: bool = False

class OpenByQueryBody(BaseModel):
    text: str = Field(..., min_length=2, description="Volná věta, např. 'načti PID 91000 TSW CIP'")

# =======================
#     POMOCNÉ FUNKCE
# =======================
def _safe_list_pdfs() -> List[str]:
    """Seznam názvů PDF (basename) v PID_DATA_DIR."""
    if not os.path.isdir(PID_DATA_DIR):
        return []
    result = []
    for fn in os.listdir(PID_DATA_DIR):
        path = os.path.join(PID_DATA_DIR, fn)
        if os.path.isfile(path) and os.path.splitext(fn)[1].lower() in ALLOWED_EXTS:
            result.append(fn)
    return result

def _sanitize_name(s: str) -> str:
    """Normalizace pro porovnávání názvů."""
    return re.sub(r"\s+", " ", s.replace("_", " ").strip()).lower()

def _match_exact_or_none(name_like: str) -> Optional[str]:
    """
    Zkusí najít soubor přesný/velmi blízký názvu.
    - Přijme '91000_TSW_CIP_-_PID' i '91000 TSW CIP - PID' i s '.pdf'
    """
    want = _sanitize_name(name_like)
    if not want.endswith(".pdf"):
        want_pdf = f"{want}.pdf"
    else:
        want_pdf = want

    candidates = _safe_list_pdfs()
    for fn in candidates:
        if _sanitize_name(fn) == want_pdf:
            return fn

    # fallback: zkuste shodu bez '.pdf'
    base_want = want[:-4] if want.endswith(".pdf") else want
    for fn in candidates:
        if _sanitize_name(os.path.splitext(fn)[0]) == base_want:
            return fn

    return None

def _search_by_tokens(text: str) -> List[str]:
    """
    Lehká heuristika:
    1) vytáhne kód (4–6 číslic) – priorita.
    2) jinak tokenizuje slova (min 2 znaky) a dělá substring match.
    Vrací seznam kandidátů (basename).
    """
    files = _safe_list_pdfs()
    if not files:
        return []

    norm_files = [(fn, _sanitize_name(fn)) for fn in files]
    q = _sanitize_name(text)

    # 1) pokus o kód (např. 91000)
    m = re.search(r"\b(\d{4,6})\b", q)
    if m:
        code = m.group(1)
        hits = [fn for fn, s in norm_files if code in s]
        if hits:
            # preferuj ty, které také obsahují 'pid'
            pid_hits = [fn for fn, s in norm_files if code in s and "pid" in s]
            return pid_hits or hits

    # 2) tokeny
    tokens = [t for t in re.split(r"[^0-9a-zA-Z]+", q) if len(t) >= 2]
    if not tokens:
        return []

    def score(s: str) -> int:
        return sum(1 for t in tokens if t in s)

    scored = [(fn, score(s)) for fn, s in norm_files]
    max_score = max((sc for _, sc in scored), default=0)
    if max_score == 0:
        return []

    return [fn for fn, sc in scored if sc == max_score]

# =======================
#     RAG ENDPOINTY
# =======================
@router.post("/reindex")
def reindex(body: ReindexBody = ReindexBody()) -> Dict[str, Any]:
    try:
        stats = rag.reindex(force_ocr=bool(body.force_ocr))
        return {"status": "ok", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search")
def search(body: SearchBody) -> Dict[str, Any]:
    try:
        results = rag.search(body.query, body.top_k)
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/find_tag")
def find_tag(body: TagBody) -> Dict[str, Any]:
    try:
        hits = rag.find_tag(body.tag)
        return {"status": "ok", "matches": hits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ocr_preview")
def ocr_preview(page: int = Query(1, ge=1)) -> Dict[str, Any]:
    """
    Vrátí čistý OCR text z vybrané stránky PID PDF (pro debug).
    """
    rag._lazy_load()
    if not rag.meta:
        return {"status": "empty_index"}

    if page > len(rag.meta):
        page = len(rag.meta)

    text = rag.meta[page - 1].get("text", "")
    ocr_flag = rag.meta[page - 1].get("ocr", False)
    tags = rag.meta[page - 1].get("tags", [])
    return {
        "status": "ok",
        "page": page,
        "ocr": ocr_flag,
        "tags": tags,
        "text_excerpt": text[:1500]
    }

# =======================
#   SERVÍROVÁNÍ PDF
# =======================
@router.get("/file/{name}")
def get_pid_file(name: str):
    """
    Stáhne/zobrazí konkrétní PDF podle názvu (bezpečně).
    Podporuje:
      /pids/file/91000_TSW_CIP_-_PID
      /pids/file/91000 TSW CIP - PID
      /pids/file/91000_TSW_CIP_-_PID.pdf
    """
    # Přímá shoda
    fn = _match_exact_or_none(name)
    if not fn:
        # Pokus o „chytré“ hledání podle tokenů (např. když je název trochu odlišný)
        candidates = _search_by_tokens(name)
        if len(candidates) == 1:
            fn = candidates[0]

    if not fn:
        raise HTTPException(status_code=404, detail=f"PID PDF nenalezeno pro '{name}'")

    path = os.path.join(PID_DATA_DIR, fn)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Soubor neexistuje: {fn}")

    return FileResponse(path, media_type="application/pdf", filename=fn)

@router.post("/open_by_query")
def open_by_query(body: OpenByQueryBody) -> Dict[str, Any]:
    """
    Vezme volnou větu (např. 'načti PID 91000 TSW CIP') a vrátí
    - přímo jeden nalezený soubor (status=ok + url),
    - nebo víc kandidátů k výběru (status=ambiguous),
    - nebo not_found.
    """
    # 1) nejdřív zkus přesnou shodu názvu
    direct = _match_exact_or_none(body.text)
    if direct:
        return {
            "status": "ok",
            "file": direct,
            "url": f"/pids/file/{direct}"
        }

    # 2) heuristické vyhledání
    candidates = _search_by_tokens(body.text)

    if not candidates:
        return {"status": "not_found", "message": "Nepodařilo se najít žádný PID PDF."}

    if len(candidates) == 1:
        fn = candidates[0]
        return {"status": "ok", "file": fn, "url": f"/pids/file/{fn}"}

    # více kandidátů – vrať uživateli na výběr
    return {
        "status": "ambiguous",
        "candidates": [{"file": fn, "url": f"/pids/file/{fn}"} for fn in candidates]
    }
