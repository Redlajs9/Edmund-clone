# backend/services/orchestrator.py
import os
import json
from typing import Any, Dict, List

from openai import OpenAI
from .prompts import SYSTEM_PROMPT, FEWSHOTS
from .tools import OPENAI_TOOLS, TOOL_IMPLS
from .rag import RagStore

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


class Orchestrator:
    """
    Orchestruje LLM volání:
    - přidá systémový prompt a few-shots
    - pokud je k dispozici RAG kontext, přidá jej do system zprávy
    - povolí function-calling (find_valve/query_events/get_system_state)
    - postará se o vykonání tool-calls a vrácení finální odpovědi
    """
    def __init__(self, model: str | None = None, temperature: float = 0.2):
        self.client = OpenAI()
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.rag = RagStore(self.client)
        self.rag.load()  # tiché; pokud index není, jede se bez RAG
        # možnost vypnout LLM (např. při absenci klíče / mock režim)
        self.enabled = bool(os.getenv("OPENAI_API_KEY")) and os.getenv("LLM_MODE", "").lower() != "mock"

    def _ctx_messages(self, question: str) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = []
        hits = self.rag.search(question, k=4)
        if hits:
            ctx = "\n\n--- KONTEXT ---\n" + "\n\n".join([f"[{i+1}] {t}" for i, (t, _) in enumerate(hits)])
            msgs.append({"role": "system", "content": ctx})
        return msgs

    def answer(self, question: str) -> Dict[str, Any]:
        # Bez LLM vrať přátelský fallback (endpoint nespadne)
        if not self.enabled:
            return {
                "answer": "LLM je vypnuté (není OPENAI_API_KEY nebo LLM_MODE=mock).",
                "tools_used": []
            }

        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages += FEWSHOTS
        messages += self._ctx_messages(question)
        messages.append({"role": "user", "content": question})

        tools_used: List[str] = []

        try:
            # max 3 kola tool-calls
            for _ in range(3):
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=OPENAI_TOOLS,
                    tool_choice="auto",
                    temperature=self.temperature,
                )
                msg = resp.choices[0].message

                # 1) pokud nejsou tool_calls, máme finální odpověď
                if not getattr(msg, "tool_calls", None):
                    return {"answer": msg.content or "", "tools_used": tools_used}

                # 2) přidej assistant message s tool_calls do historie
                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                })

                # 3) vykonej nástroje a přidej 'tool' zprávy s tool_call_id
                for tc in msg.tool_calls:
                    name = tc.function.name
                    args = {}
                    if tc.function.arguments:
                        try:
                            args = json.loads(tc.function.arguments)
                        except Exception:
                            args = {}

                    tools_used.append(name)
                    impl = TOOL_IMPLS.get(name)

                    if impl is None:
                        result = {"error": f"Unknown tool '{name}'", "received_args": args}
                    else:
                        try:
                            result = impl(**args)
                        except TypeError as e:
                            result = {"error": f"Bad arguments: {e}", "received_args": args}
                        except Exception as e:
                            result = {"error": f"Tool {name} failed: {e.__class__.__name__}: {e}"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,   # DŮLEŽITÉ: vazba na assistant.tool_calls
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False),
                    })

            # Bezpečný fallback po 3 kolech
            return {"answer": "Nepodařilo se dokončit odpověď po volání nástrojů.", "tools_used": tools_used}

        except Exception as e:
            # Vrátíme čitelnou chybu namísto 500
            return {"answer": f"LLM chyba: {e.__class__.__name__}: {e}", "tools_used": tools_used}
