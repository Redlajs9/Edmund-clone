from fastapi import APIRouter
from domain.rules import analyze_missing
from models.chat import ChatRequest, ChatResponse

router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    missing, why = analyze_missing(req.question)
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
                "Přiložit popisy sekvencí (CSV/PDF) pro mapování kroků."
            ],
        )
    return ChatResponse(status="ok", answer="✅ (placeholder) Mám vše potřebné.")
