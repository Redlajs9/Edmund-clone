# backend/api/routers/unified.py
from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any, Dict
import os, re, json, numpy as np, sqlite3, inspect

# ---- config / paths ----
LOGIC_URL_PATH = "/logic/ask"   # historický koment, voláme přímo funkci -> bez HTTP hopu
SQLITE = os.getenv("IO_DB_PATH", "/app/data/io.db")
HWF_IDX = os.getenv("RAG_HWF_INDEX_PATH", "/app/data/faiss_hwf.index")
HWF_MAP = os.getenv("RAG_HWF_STORE_PATH", "/app/data/hwf_store.npy")

router = APIRouter(prefix="/chat", tags=["chat-unified"])

# =======================
#        MODELY
# =======================
class ChatReq(BaseModel):
    question: str
    top_k: int = 5
    force: Optional[str] = None  # "logic" | "chat" (volitelný override z UI)

# =======================
#   HEURISTIKY / ROUTING
# =======================
PLC_TAG_RE = re.compile(r'\b9\d{4}[A-Z]{2}\d{3}\b')         # např. 91201VA001
TIA_NAME_RE = re.compile(r'\b(FB|FC|OB|DB|GlobalDB)_[0-9A-Za-z_]+\b', re.IGNORECASE)
SEQ_RE = re.compile(r'\bSEQ0?\d{1,3}\b', re.IGNORECASE)
FB_SHORT_RE = re.compile(r'\bFB\s*\d+\b', re.IGNORECASE)

PLC_KEYWORDS = (
    "cip","ventil","ventile","valve","dávkov","dose","seq","heizen","heating",
    "desi","desinf","rinse","safety","pid","ufa","proleit","brewmaxx","step","krok"
)

def looks_like_plc_logic(q: str) -> bool:
    ql = q.lower()
    if TIA_NAME_RE.search(q): return True
    if SEQ_RE.search(q): return True
    if PLC_TAG_RE.search(q): return True
    if FB_SHORT_RE.search(q): return True
    if any(k in ql for k in PLC_KEYWORDS): return True
    if any(k in ql for k in ["co dělá", "jaká je logika", "které podmínky", "parametry", "vstupy", "výstupy"]):
        return True
    return False

def pick_route(q: str, top_k: int, force: Optional[str]) -> str:
    if force in ("logic", "chat"):
        return force
    if os.path.exists(HWF_IDX) and os.path.exists(HWF_MAP) and looks_like_plc_logic(q):
        return "logic"
    return "chat"

# --- vnitřní volání na již existující routery (bez HTTP hopu) ---
# Pozn.: Importy na konci modulu FastAPI se nemají rád, tady jsou bezpečně nahoře.
from . import chat as base_chat
from . import logic as hwf_logic  # očekává se, že obsahuje AskReq + ask(...)

# Helper: zavolej sync/async funkci jednotně
async def _maybe_call_chat(question: str, fastapi_request: Request) -> Any:
    """
    Očekává, že base_chat obsahuje endpoint-like funkci 'chat(...)' (async nebo sync),
    která přijímá buď Pydantic model, nebo dict, a vrací dict/objekt s klíčem 'answer'.
    """
    func = getattr(base_chat, "chat", None)
    if func is None:
        raise HTTPException(500, "base_chat.chat není dostupné")

    # Preferovat volání s Request, pokud to signatura vyžaduje
    try:
        if inspect.iscoroutinefunction(func):
            resp = await func({"question": question}, fastapi_request)  # type: ignore[arg-type]
        else:
            resp = func({"question": question}, fastapi_request)        # type: ignore[misc]
        return resp
    except TypeError:
        # Některé implementace mají signaturu jen (payload)
        if inspect.iscoroutinefunction(func):
            resp = await func({"question": question})  # type: ignore[misc]
        else:
            resp = func({"question": question})        # type: ignore[misc]
        return resp

def _normalize_chat_response(resp: Any) -> Dict[str, Any]:
    """
    Vrátí normalizovaný dict s klíčem 'answer' (pro sjednocení odpovědi).
    """
    if isinstance(resp, dict):
        if "answer" in resp:
            return {"answer": resp["answer"]}
        # někdy se vrací {"mode":"chat","answer":"..."} – nechme projít
        if "mode" in resp and "answer" in resp:
            return {"answer": resp["answer"]}
        # fallback – serializace do textu
        return {"answer": json.dumps(resp, ensure_ascii=False)}
    # pokud je to plain string
    if isinstance(resp, str):
        return {"answer": resp}
    # jinak to serializuj
    return {"answer": json.dumps(resp, ensure_ascii=False)}

def format_fb_answer(resp: dict) -> str:
    # vezmi první shodu
    m = resp["matches"][0]["info"]
    lines = []
    header = f"**{m['name']}** — {m.get('title','').strip()}"
    if m.get("comment"): header += f"\n\n_{m['comment'].strip()}_"
    lines.append(header)

    for sec in m.get("sections", []):
        sec_title = sec["section"].upper()
        # zajímají tě zejména INPUT/OUTPUT/IN_OUT/STATIC:
        if sec_title in {"INPUT", "OUTPUT", "IN_OUT", "STATIC"}:
            lines.append(f"\n**{sec_title}**")
            for mem in sec["members"]:
                nm = mem["name"]; dt = mem["datatype"]; cm = mem.get("comment","")
                if cm:
                    lines.append(f"- `{nm}: {dt}` — {cm}")
                else:
                    lines.append(f"- `{nm}: {dt}`")
    return "\n".join(lines)

# =======================
#        ENDPOINT
# =======================
@router.post("/unified")
async def unified(req: ChatReq, fastapi_request: Request):
    """
    Sjednocený vstup pro UI:
      - automaticky volí mezi HWF/PLC logikou a běžným chatem
      - možnost vynutit přes req.force ∈ {"logic","chat"}
    Výstup sjednocuje klíče: {mode: "logic"|"chat", answer: "...", used_blocks:[...]}
    """
    route = pick_route(req.question, req.top_k, req.force)

    # 1) LOGIC větev (HWF / PLC)
    if route == "logic":
        # Přímé volání logic routeru v paměti (bez HTTP)
        try:
            # Očekávané rozhraní: AskReq(question:str, top_k:int) → dict se stringem "answer" + "used_blocks"
            data = hwf_logic.ask(hwf_logic.AskReq(question=req.question, top_k=req.top_k))  # type: ignore[attr-defined]
            # Ujistíme se, že to je JSON serializovatelné
            payload = {
                "mode": "logic",
                **(data if isinstance(data, dict) else {"answer": str(data)})
            }
            return JSONResponse(content=jsonable_encoder(payload))
        except HTTPException as e:
            # Specificky – pokud logic indikuje, že není index (např. 400), spadni do chatu
            if e.status_code in (400, 404):
                route = "chat"
            else:
                raise
        except Exception as e:
            # Jakákoliv jiná chyba v logic → fallback do chatu (aby UI nezůstalo bez odpovědi)
            route = "chat"

    # 2) CHAT větev (fallback i primární)
    # Zavolej interní chat without HTTP
    resp = await _maybe_call_chat(req.question, fastapi_request)
    norm = _normalize_chat_response(resp)
    return JSONResponse(content=jsonable_encoder({
        "mode": "chat",
        "answer": norm.get("answer", ""),
        "used_blocks": []
    }))
