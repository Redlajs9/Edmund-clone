# backend/api/routers/hwf.py
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import os, glob, re
from xml.etree import ElementTree as ET

router = APIRouter(prefix="/hwf", tags=["hwf"])

HWF_DIR = os.getenv("HWF_DIR", "/app/data/HWF")

# 1) helpery -----------------------------------------------------

def _norm_fb_name(raw: str) -> str:
    """FB_105 → FB105; odstraň mezery; uppercase."""
    s = raw.strip().upper().replace(" ", "")
    return s.replace("FB_", "FB")

def _list_xml() -> List[str]:
    paths = glob.glob(os.path.join(HWF_DIR, "FB*.xml"))
    return paths or glob.glob(os.path.join(HWF_DIR, "*.xml"))

def _text(e: Optional[ET.Element], tag: str, ns=False) -> str:
    if e is None: return ""
    if ns:
        n = e.find(tag)
    else:
        n = e.find(tag)
    return (n.text or "").strip() if n is not None and n.text else ""

def _first(root: ET.Element, tag_candidates: List[str]) -> Optional[ET.Element]:
    """Najdi první existující uzel z kandidátů (s i bez namespace)."""
    for t in tag_candidates:
        # wildcards na namespace: { * }Tag
        node = root.find(f".//{{*}}{t}")
        if node is not None:
            return node
    return None

def _findall(e: ET.Element, tag: str) -> List[ET.Element]:
    return e.findall(f"./{{*}}{tag}") if e is not None else []

def _parse_fb(path: str) -> Optional[Dict[str, Any]]:
    """
    Vrátí {name,title,comment,sections:[{section, members:[{name,datatype,comment}]}]}
    nebo None, pokud soubor neobsahuje FB.
    """
    try:
        root = ET.parse(path).getroot()

        # FB nebo FBType (ignoruj namespace)
        fb = _first(root, ["SW.Blocks.FB", "SW.Blocks.FBType"])
        if fb is None:
            return None

        attrs = _first(fb, ["AttributeList"])
        name    = _text(attrs, "{*}Name", True)    or _text(attrs, "Name")
        title   = _text(attrs, "{*}Title", True)   or _text(attrs, "Title")
        comment = _text(attrs, "{*}Comment", True) or _text(attrs, "Comment")

        iface = _first(fb, ["Interface"])
        sections: List[Dict[str, Any]] = []
        if iface is not None:
            secs = _first(iface, ["Sections"])
            if secs is not None:
                for sec in _findall(secs, "Section"):
                    sec_name = sec.get("Name", "")
                    members = []
                    for m in _findall(sec, "Member"):
                        members.append({
                            "name": m.get("Name", ""),
                            "datatype": m.get("Datatype", ""),
                            "comment": _text(m, "{*}Comment", True) or _text(m, "Comment"),
                        })
                    sections.append({"section": sec_name, "members": members})

        return {"name": name, "title": title, "comment": comment, "sections": sections}
    except Exception:
        return None

# 2) modely ------------------------------------------------------

class FBReq(BaseModel):
    name: str  # "FB105" nebo "FB_105" nebo celý název

# 3) endpointy ---------------------------------------------------

@router.post("/fb_info")
def fb_info(req: FBReq) -> Dict[str, Any]:
    """
    Vyhledá FB podle jména z AttributeList/Name (např. 'FB105').
    Bere i prefixové shody (FB105_*).
    """
    if not os.path.isdir(HWF_DIR):
        raise HTTPException(500, f"HWF_DIR neexistuje: {HWF_DIR}")

    want = _norm_fb_name(req.name)
    matches = []

    for p in _list_xml():
        info = _parse_fb(p)
        if not info or not info.get("name"):
            continue
        n = _norm_fb_name(info["name"])
        if n == want or n.startswith(f"{want}_"):
            matches.append({"file": os.path.basename(p), "info": info})

    if not matches:
        raise HTTPException(404, f"FB '{req.name}' nebyl nalezen v {HWF_DIR}")
    return {"status": "ok", "matches": matches}

@router.get("/by_file")
def by_file(name: str = Query(..., description="Přesný název XML souboru v HWF_DIR")) -> Dict[str, Any]:
    """
    PŘÍMÉ ČTENÍ PODLE SOUBORU – pro případy jako
    'FB_105_SEQ005_91201 CIP Kreis 1.xml'.
    """
    if not os.path.isdir(HWF_DIR):
        raise HTTPException(500, f"HWF_DIR neexistuje: {HWF_DIR}")

    path = os.path.join(HWF_DIR, name)
    if not os.path.isfile(path):
        # Zkus tolerantně: najdi první soubor, který obsahuje všechny tokeny
        tokens = [t for t in re.split(r"[ _\-\.]+", name) if t]
        cand = None
        for p in _list_xml():
            fn = os.path.basename(p)
            if all(t.lower() in fn.lower() for t in tokens):
                cand = p; break
        if not cand:
            raise HTTPException(404, f"Soubor '{name}' v {HWF_DIR} nenalezen")
        path = cand

    info = _parse_fb(path)
    if not info:
        raise HTTPException(422, f"Soubor '{os.path.basename(path)}' neobsahuje FB nebo je nečitelný")
    return {"status": "ok", "file": os.path.basename(path), "info": info}

@router.get("/search")
def search(q: str = Query(..., description="Hledání podle tokenů: např. 'FB_105 91201 SEQ005'")) -> Dict[str, Any]:
    """
    Vyhledá soubory dle tokenů (části názvu). Hodí se pro '91201'.
    """
    if not os.path.isdir(HWF_DIR):
        raise HTTPException(500, f"HWF_DIR neexistuje: {HWF_DIR}")

    tokens = [t for t in re.split(r"[ _\-\.]+", q) if t]
    found = []
    for p in _list_xml():
        fn = os.path.basename(p)
        if all(t.lower() in fn.lower() for t in tokens):
            found.append(fn)
    return {"status": "ok", "files": found}

@router.get("/debug/first_fb")
def debug_first_fb() -> Dict[str, Any]:
    """
    Vrátí první úspěšně rozparsovaný FB – pro rychlou verifikaci parseru.
    """
    if not os.path.isdir(HWF_DIR):
        raise HTTPException(500, f"HWF_DIR neexistuje: {HWF_DIR}")

    for p in _list_xml():
        info = _parse_fb(p)
        if info:
            return {"ok": True, "file": os.path.basename(p), "info": info}
    return {"ok": False, "msg": "V žádném XML jsem nenašel FB definici."}
