# backend/services/tools.py
import os
import sqlite3
import urllib.parse as _up
from typing import Any, Dict, List, Optional

# --- RYCHLÝ PDF text (PyMuPDF) + fallback pypdf ---
try:
    import fitz  # PyMuPDF (rychlé)
except Exception:
    fitz = None  # type: ignore

try:
    from pypdf import PdfReader  # fallback (pomalejší)
except Exception:
    PdfReader = None  # type: ignore

# Cesty: počítáme relativně od rootu repa (o adresář výš z backend/)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
IO_DB = os.getenv("IO_DB_PATH", os.path.join(ROOT, "data", "io.db"))
ELECTRICAL_DIR = os.getenv("ELECTRICAL_DIR", os.path.join(ROOT, "data", "electrical"))
PREVIEWS_DIR = os.getenv("PREVIEWS_DIR", os.path.join(ROOT, "data", "previews"))
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "")  # např. http://localhost:8000


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


def _norm_tag(s: str) -> str:
    """Normalizace pro robustnější porovnání (bez whitespace, uppercase)."""
    return "".join((s or "").split()).upper()


def _page_snippet(text: str, needle: str, ctx: int = 60) -> str:
    """Vrátí krátký kontext kolem nálezu pro UX."""
    up = text.upper()
    i = up.find(needle.upper())
    if i == -1:
        return ""
    start = max(0, i - ctx)
    end = min(len(text), i + len(needle) + ctx)
    return text[start:end].replace("\n", " ").strip()


def _static_preview_urls(rel_pdf: str, page_idx: int) -> Dict[str, Optional[str]]:
    """
    Z rel PDF cesty (např. 'data/electrical/Folder/Doc.pdf') a 0-index stránky
    složí URL i diskovou cestu pro statický náhled JPG v data/previews.
    Vrátí dict s klíči: url, abs_url (nebo None pokud soubor neexistuje).
    """
    # relativní cesta PDF vůči data/electrical
    elec_root = os.path.join(ROOT, "data", "electrical")
    pdf_abs = os.path.join(ROOT, rel_pdf)
    rel_from_elec = os.path.relpath(pdf_abs, elec_root)
    base_no_ext, _ = os.path.splitext(rel_from_elec)
    rel_jpg_path = f"{base_no_ext}_p{page_idx+1:04d}.jpg".replace("\\", "/")

    # disková cesta k JPG a veřejná URL
    jpg_abs = os.path.join(PREVIEWS_DIR, rel_jpg_path)
    # URL-encode (ponecháme lomítka)
    url = "/previews/" + _up.quote(rel_jpg_path, safe="/")
    abs_url = f"{PUBLIC_API_BASE_URL}{url}" if PUBLIC_API_BASE_URL else None

    if os.path.exists(jpg_abs):
        return {"url": url, "abs_url": abs_url}
    # náhled není předrenderovaný
    return {"url": None, "abs_url": None}


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
# Tool: list_valves_by_prefix
# --------------------------
def list_valves_by_prefix(prefix: str, limit: int = 200) -> Dict[str, Any]:
    """
    Vrátí ventily (TAGy obsahující 'VA') začínající na zadaný prefix (např. '91002').
    Pro každý TAG vrátí rozdělené vstupy/výstupy.
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
# NEW Tool: find_electrical_drawing (rychlé přes PyMuPDF + fallback pypdf)
# --------------------------
def find_electrical_drawing(
    tag: str,
    folder: Optional[str] = None,
    max_files: int = 200,
    max_pages_per_file: int = 300,
    stop_after_matches: int = 20,
) -> Dict[str, Any]:
    """
    Prohledá PDF výkresy ve složce (default: data/electrical) a vrátí seznam
    [soubor, strana, snippet, preview_url, preview_static_url], kde se TAG vyskytuje v textové vrstvě PDF.

    Výkonové limity:
      - max_files: kolik PDF maximálně otevřít
      - max_pages_per_file: kolik stránek max číst z jednoho PDF
      - stop_after_matches: po kolika nálezech celkově skončit
    """
    if not tag or not tag.strip():
        return {"query": tag, "error": "empty_tag"}

    base = folder or ELECTRICAL_DIR
    if not os.path.isdir(base):
        return {"query": tag, "dir": base, "error": "directory_not_found"}

    needle_norm = _norm_tag(tag)
    matches: List[Dict[str, Any]] = []
    scanned = 0

    def _add_match(fpath: str, page_idx: int, text: str):
        rel = os.path.relpath(fpath, ROOT).replace("\\", "/")

        # dynamický (query string bezpečně zakódujeme)
        qs = _up.urlencode({"file": rel, "page": page_idx + 1, "tag": tag})
        rel_preview = f"/preview/electrical?{qs}"
        abs_preview = f"{PUBLIC_API_BASE_URL}{rel_preview}" if PUBLIC_API_BASE_URL else None

        # statický (už vrací URL-encoded)
        static = _static_preview_urls(rel, page_idx)
        static_url = static["url"]
        static_abs = static["abs_url"]

        matches.append({
            "file": rel,
            "page": page_idx + 1,  # 1-index
            "snippet": _page_snippet(text, tag, 60),
            "preview_url": rel_preview,
            "preview_absolute_url": abs_preview,
            "preview_static_url": static_url,
            "preview_static_absolute_url": static_abs,
        })

    for root, _, files in os.walk(base):
        for fn in files:
            if not fn.lower().endswith(".pdf"):
                continue
            fpath = os.path.join(root, fn)
            scanned += 1
            if scanned > max_files:
                break

            # 1) Rychlá cesta: PyMuPDF
            if fitz is not None:
                try:
                    doc = fitz.open(fpath)
                    pages_to_scan = min(len(doc), max_pages_per_file)
                    for pidx in range(pages_to_scan):
                        page = doc.load_page(pidx)
                        text = page.get_text("text") or ""
                        if needle_norm in _norm_tag(text):
                            _add_match(fpath, pidx, text)
                            if len(matches) >= stop_after_matches:
                                break
                    doc.close()
                    if len(matches) >= stop_after_matches:
                        break
                    # už jsme soubor zkusili; jdi na další
                    continue
                except Exception:
                    # spadlo – zkus fallback
                    pass

            # 2) Fallback: pypdf (pomalejší)
            if PdfReader is not None:
                try:
                    reader = PdfReader(fpath)
                    pages_to_scan = min(len(reader.pages), max_pages_per_file)
                    for pidx in range(pages_to_scan):
                        try:
                            text = reader.pages[pidx].extract_text() or ""
                            if needle_norm in _norm_tag(text):
                                _add_match(fpath, pidx, text)
                                if len(matches) >= stop_after_matches:
                                    break
                        except Exception:
                            continue
                    if len(matches) >= stop_after_matches:
                        break
                except Exception:
                    # nepovedlo se otevřít, pokračuj
                    continue

        if len(matches) >= stop_after_matches:
            break

    return {
        "query": tag,
        "dir": os.path.relpath(base, ROOT).replace("\\", "/"),
        "count": len(matches),
        "matches": matches,
    }


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
            "name": "find_electrical_drawing",
            "description": "Vyhledá v PDF výkresech strany, kde se vyskytuje daný TAG (textová vrstva).",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "folder": {"type": "string", "description": "Kořenová složka s PDF (default data/electrical)"},
                    "max_files": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
                    "max_pages_per_file": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 300},
                    "stop_after_matches": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 20}
                },
                "required": ["tag"]
            }
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
    "find_electrical_drawing": find_electrical_drawing,
    "get_system_state": get_system_state,
    "query_events": query_events,
}
