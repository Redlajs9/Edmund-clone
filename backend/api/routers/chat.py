# backend/api/routers/chat.py
import re
from fastapi import APIRouter
from backend.models.chat import ChatRequest, ChatResponse
from backend.domain.rules import analyze_missing
from backend.services.orchestrator import Orchestrator
from backend.services.tools import list_valves_by_prefix

router = APIRouter(tags=["chat"])
orc = Orchestrator()


@router.post("/chat", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest):
    q = (req.question or "").strip()

    # 0) Rychlá deterministická zkratka (bez LLM) pro prefixové dotazy:
    #    - "vypiš všechny ventily pro tank 91002"
    #    - "vypiš ventily 91002"
    #    - "91002x"
    m = (
        re.search(r"(?:ventil(?:y|ů)?\s+(?:pro\s+tank\s+)?)?(\d{3,6})\s*(?:x)?\b", q.lower())
        or re.search(r"\b(\d{3,6})x\b", q.lower())
    )
    if m:
        prefix = m.group(1)
        data = list_valves_by_prefix(prefix=prefix, limit=200)
        if data.get("count", 0) > 0:
            items = list(data["items"].items())[:50]
            lines = []
            for tag, io in items:
                e = ", ".join([f"{i['io_type']} {i['address']}" for i in io["inputs"]]) or "-"
                a = ", ".join([f"{o['io_type']} {o['address']}" for o in io["outputs"]]) or "-"
                lines.append(f"{tag}: Vstupy [{e}] | Výstupy [{a}]")
            tail = "" if data["count"] <= 50 else f"\n… zobrazeno 50 z {data['count']} tagů."
            return ChatResponse(status="ok", answer="\n".join(lines) + tail, tools_used=["list_valves_by_prefix"])

    # 1) Kontrola chybějících zdrojů
    missing, why = analyze_missing(q)
    if missing:
        return ChatResponse(
            status="insufficient_knowledge",
            message="Na zodpovězení tohoto dotazu nemám dostatečnou dokumentaci.",
            missing=missing,
            why_needed={k: why[k] for k in missing if k in why},
            how_to_connect_next=[
                "Nahrát P&ID (PDF/DWG) + metadata.",
                "Připojit ProLeiT MSSQL (read-only) + schema.",
                "Dodat elektro výkresy (PDF/EPLAN) + seznam IO.",
                "Přiložit popisy sekvencí (CSV/PDF) pro mapování kroků.",
            ],
            tools_used=[],
        )

    # 2) Orchestrátor (RAG + tools + LLM)
    result = orc.answer(q)
    return ChatResponse(
        status="ok",
        answer=result.get("answer", ""),
        tools_used=result.get("tools_used", []),
    )
