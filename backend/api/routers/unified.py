# backend/api/routers/unified.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import os, re, json, numpy as np, sqlite3

# ---- config / paths ----
LOGIC_URL_PATH = "/logic/ask"   # vnitřní delegace (stejný proces)
SQLITE = os.getenv("IO_DB_PATH", "/app/data/io.db")
HWF_IDX = os.getenv("RAG_HWF_INDEX_PATH", "/app/data/faiss_hwf.index")
HWF_MAP = os.getenv("RAG_HWF_STORE_PATH", "/app/data/hwf_store.npy")

router = APIRouter(prefix="/chat", tags=["chat-unified"])

class ChatReq(BaseModel):
    question: str
    top_k: int = 5
    force: str | None = None  # "logic" | "chat" (volitelný override z UI)

def looks_like_plc_logic(q: str) -> bool:
    ql = q.lower()
    # 1) příznaky z TIA: FB_*, FC_*, OB_*, DB_*, GlobalDB_*, SEQxxx, 91xxx tagy, "CIP", "Ventil", "VA00x", "PID", "Safety"
    if re.search(r'\b(FB|FC|OB|DB|GlobalDB)_[0-9A-Za-z_]+', q): return True
    if re.search(r'\bSEQ0?\d{1,3}\b', q): return True
    if re.search(r'\b9\d{4}[A-Z]{2}\d{3}\b', q): return True  # např. 91201VA001
    if any(k in ql for k in ["cip", "ventil", "dávkov", "seq", "heizen", "desi", "dosi", "rinse", "safety", "pid", "ufa", "proleit"]):
        return True
    # 2) dotazy typu "co dělá/parametry/rozhraní sítě"
    if any(k in ql for k in ["co dělá", "jaká je logika", "které podmínky", "parametry", "vstupy", "výstupy"]):
        return True
    return False

# jednoduchá interní "router" funkce: preferuj LOGIC, pokud existuje HWF index a dotaz tak vypadá
def pick_route(q: str, top_k: int, force: str | None):
    if force in ("logic", "chat"):
        return force
    if os.path.exists(HWF_IDX) and os.path.exists(HWF_MAP) and looks_like_plc_logic(q):
        return "logic"
    return "chat"

# --- vnitřní volání na již existující routery (bez HTTP hopu) ---
# ✅ RELATIVNÍ IMPORTY (správné)
from . import chat as base_chat
from . import logic as hwf_logic

@router.post("/unified")
async def unified(req: ChatReq, fastapi_request: Request):
    route = pick_route(req.question, req.top_k, req.force)

    if route == "logic":
        # přímo zavoláme funkci z logic routeru
        try:
            data = hwf_logic.ask(hwf_logic.AskReq(question=req.question, top_k=req.top_k))
            return JSONResponse(content=jsonable_encoder({
                "mode": "logic",
                **data
            }))
        except HTTPException as e:
            # fallback: když není index, spadni do chatu
            if e.status_code in (400,):
                route = "chat"
            else:
                raise

    if route == "chat":
        # zavolej tvůj původní /chat endpoint (funkčně – ne HTTP)
        try:
            # base_chat má pravděpodobně pydantic request – adaptuj podle tvé implementace
            # Příklad: {question: "..."} -> {"answer":"..."}
            response = await base_chat.chat({"question": req.question}, fastapi_request)
            # Sjednotíme výstup:
            return JSONResponse(content=jsonable_encoder({
                "mode": "chat",
                "answer": response.get("answer") if isinstance(response, dict) else response,
                "used_blocks": []
            }))
        except Exception as e:
            raise HTTPException(500, f"Chyba v chat routě: {e}")
