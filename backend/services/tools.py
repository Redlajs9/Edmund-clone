# backend/services/tools.py
import os
import sqlite3
from typing import Any, Dict, List

# Cesty: počítáme relativně od rootu repa (o adresář výš z backend/)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IO_DB = os.getenv("IO_DB_PATH", os.path.join(ROOT, "data", "io.db"))


def _q(sql: str, params=()) -> List[Dict[str, Any]]:
    con = sqlite3.connect(IO_DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


# --------------------------
# Pomocné
# --------------------------
def _split_io(rows: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    ins = [r for r in rows if str(r.get("io_type", "")).upper().startswith("E")]
    outs = [r for r in rows if str(r.get("io_type", "")).upper().startswith("A")]

    def pick(r: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "tag": r.get("tag"),
            "io_type": r.get("io_type"),
            "address": r.get("address"),
            "datatype": r.get("datatype"),
            "desc1": r.get("desc1"),
            "desc2": r.get("desc2"),
            "comment": r.get("comment"),
        }

    return {"inputs": [pick(r) for r in ins], "outputs": [pick(r) for r in outs]}


# --------------------------
# Tool: find_valve
# --------------------------
def find_valve(tag: str) -> Dict[str, Any]:
    """Vyhledá I/O řádky pro daný tag. Vrací inputs/outputs a případné kandidáty u partial match."""
    t = (tag or "").strip()
    if not t:
        return {"query": tag, "match": "none", "error": "empty_tag"}

    exact = _q("SELECT * FROM io WHERE tag = ? ORDER BY io_type, address", (t,))
    if exact:
        return {"query": t, "match": "exact", **_split_io(exact)}

    like = f"%{t}%"
    partial = _q("SELECT * FROM io WHERE tag LIKE ? ORDER BY tag, io_type, address", (like,))
    if partial:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in partial:
            grouped.setdefault(r["tag"], []).append(r)
        candidates = {k: _split_io(v) for k, v in grouped.items()}
        return {"query": t, "match": "partial", "candidates": candidates}

    return {"query": t, "match": "none"}


# --------------------------
# NEW Tool: list_valves_by_prefix
# --------------------------
def list_valves_by_prefix(prefix: str, limit: int = 200) -> Dict[str, Any]:
    """
    Vrátí ventily (jedinečné TAGy obsahující 'VA') začínající na zadaný prefix, např. '91002'.
    Pro každý TAG vrátí rozdělené vstupy/výstupy s adresami a základním popisem.
    """
    pfx = (prefix or "").strip()
    if not pfx:
        return {"query": prefix, "error": "empty_prefix"}

    like = f"{pfx}%"
    rows = _q(
        """
        SELECT tag, io_type, address, datatype, desc1, desc2, comment
        FROM io
        WHERE tag LIKE ?
        ORDER BY tag, io_type, address
        LIMIT ?
        """,
        (like, max(1, min(int(limit or 200), 1000))),
    )

    # Filtrovat na ventily (VA) – uprav, pokud máš jinou naming konvenci
    rows = [r for r in rows if "VA" in str(r.get("tag", "")).upper()]

    grouped: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        t = r["tag"]
        g = grouped.setdefault(t, {"inputs": [], "outputs": []})
        entry = {
            "io_type": r.get("io_type"),
            "address": r.get("address"),
            "datatype": r.get("datatype"),
            "desc1": r.get("desc1"),
            "desc2": r.get("desc2"),
            "comment": r.get("comment"),
        }
        if str(r.get("io_type", "")).upper().startswith("E"):
            g["inputs"].append(entry)
        elif str(r.get("io_type", "")).upper().startswith("A"):
            g["outputs"].append(entry)

    return {"query": pfx, "count": len(grouped), "items": grouped}


# --------------------------
# (Volitelné) další ukázkové nástroje
# --------------------------
def get_system_state() -> Dict[str, Any]:
    return {
        "status": "OK",
        "uptime_sec": 12345,
        "agents": {"edmund-core": "running", "db-connector": "running"},
    }


def query_events(limit: int = 10) -> Dict[str, Any]:
    items = [
        {"ts": "2025-10-04T15:00:00Z", "lvl": "INFO", "msg": f"Heartbeat {i+1}"}
        for i in range(max(1, min(int(limit or 10), 100)))
    ]
    return {"count": len(items), "items": items}


# --------------------------
# OpenAI function-calling schémata + mapování implementací
# --------------------------
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "find_valve",
            "description": "Najde I/O adresy pro daný tag (např. 91002VA005).",
            "parameters": {
                "type": "object",
                "properties": {"tag": {"type": "string"}},
                "required": ["tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_valves_by_prefix",
            "description": "Vrátí všechny ventilové TAGy (obsahují 'VA') pro prefix, např. '91002'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prefix": {"type": "string", "description": "Začátek TAGu, např. '91002'"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
                },
                "required": ["prefix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_state",
            "description": "Vrátí aktuální stav systému/agentů.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_events",
            "description": "Vrátí poslední systémové události.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}
                },
            },
        },
    },
]

TOOL_IMPLS = {
    "find_valve": find_valve,
    "list_valves_by_prefix": list_valves_by_prefix,
    "get_system_state": get_system_state,
    "query_events": query_events,
}
