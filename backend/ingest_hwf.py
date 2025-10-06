# backend/ingest_hwf.py
import os, glob, json, sqlite3
from pathlib import Path
from xml.etree import ElementTree as ET
from typing import List, Dict
import numpy as np

# --- Cesty ---
DATA_DIR = Path("/app/data/HWF")
SQLITE = Path("/app/data/io.db")              # můžeš nechat i MSSQL přes SQLAlchemy – pro demo SQLite
FAISS_VEC_PATH = Path("/app/data/faiss_hwf.index")
FAISS_STORE_PATH = Path("/app/data/hwf_store.npy")

# --- Embedding (OpenAI) ---
import openai
openai.api_key = os.environ.get("OPENAI_API_KEY")

def embed(texts: List[str]) -> np.ndarray:
    # sloučíme do batchů kvůli rychlosti
    embs = []
    B = 96
    for i in range(0, len(texts), B):
        chunk = texts[i:i+B]
        res = openai.embeddings.create(model="text-embedding-3-large", input=chunk)
        embs.extend([d.embedding for d in res.data])
    return np.array(embs, dtype=np.float32)

# --- SQL init ---
def init_db():
    con = sqlite3.connect(SQLITE)
    cur = con.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS fb_blocks (
        id INTEGER PRIMARY KEY,
        name TEXT,         -- např. FB_105_SEQ005_91201
        title TEXT,        -- komentář/nadpis
        number TEXT,       -- číslo FB pokud je k dispozici
        path TEXT,         -- zdrojový soubor
        body TEXT          -- celý "human text" pro QA
    );
    CREATE TABLE IF NOT EXISTS fb_params (
        id INTEGER PRIMARY KEY,
        fb_id INTEGER,
        direction TEXT,    -- IN/OUT/IN_OUT/STAT
        name TEXT,
        datatype TEXT,
        comment TEXT
    );
    CREATE TABLE IF NOT EXISTS fb_networks (
        id INTEGER PRIMARY KEY,
        fb_id INTEGER,
        net_no INTEGER,
        code TEXT,         -- SCL / STL text
        comment TEXT
    );
    """)
    con.commit()
    return con

# --- Parser TIA XML (Openness) – tolerantní k variantám uzlů ---
def text_or_none(elem):
    return (elem.text or "").strip() if elem is not None else ""

def strip_ns(elem):
    """Odstraní XML namespaces, aby šly používat plain tagy (fix 'prefix ns not found')."""
    for e in elem.iter():
        if '}' in e.tag:
            e.tag = e.tag.split('}', 1)[1]
    return elem

def parse_fb_xml(path: Path) -> Dict:
    tree = ET.parse(path)
    root = strip_ns(tree.getroot())

    # heuriticky najdeme elementy FB/Block
    name = root.attrib.get("Name") or root.findtext(".//SW.Blocks.GlobalDB/AttributeList/Name", default="")
    if not name:
        name = root.findtext(".//*[@Name]", default="")
    title = root.findtext(".//Title", default="")
    number = root.findtext(".//BlockNumber", default="")

    # interface params
    params = []
    for dir_tag in ["Input", "Output", "InOut", "Static", "Temp"]:
        for p in root.findall(f".//{dir_tag}//Member"):
            params.append({
                "direction": ("IN" if dir_tag=="Input" else
                              "OUT" if dir_tag=="Output" else
                              "IN_OUT" if dir_tag=="InOut" else
                              "STAT" if dir_tag=="Static" else "TEMP"),
                "name": p.attrib.get("Name",""),
                "datatype": (p.findtext("Datatype", default="") or p.attrib.get("Datatype","")),
                "comment": p.findtext("Comment", default="")
            })

    # networks (SCL/STL body se v exportech liší – zkusíme oboje)
    nets = []
    # SCL zdroj bývá v SW.Blocks.CompileUnit/Source (někdy Code/StructuredText)
    net_candidates = root.findall(".//SW.Blocks.CompileUnit/Source") or \
                     root.findall(".//SW.Blocks.CompileUnit/Code") or \
                     root.findall(".//Source")
    if net_candidates:
        # SCL text v jednom bloku
        code_text = "\n".join([text_or_none(nc) for nc in net_candidates]).strip()
        if code_text:
            nets.append({"net_no": 1, "code": code_text, "comment": ""})
    else:
        # Ladder/FBD sítě – posbíráme komentáře a pseudo-text
        for i, n in enumerate(root.findall(".//Network"), start=1):
            cmt = n.findtext("Comment", default="")
            code = ET.tostring(n, encoding="unicode")  # fallback – uložíme XML sítě
            nets.append({"net_no": i, "code": code, "comment": cmt})

    # human-readable body pro RAG
    lines = [f"FB {name} (#{number}) – {title}"]
    if params:
        lines.append("PARAMS:")
        for p in params:
            lines.append(f"- {p['direction']:6} {p['name']}: {p['datatype']}  // {p['comment'] or ''}")
    if nets:
        lines.append("NETWORKS/CODE:")
        for n in nets:
            preview = (n["code"][:2000])  # omezíme
            lines.append(f"[NW {n['net_no']}] {n['comment']}\n{preview}")
    body_text = "\n".join(lines)

    return {
        "name": name or path.stem,
        "title": title,
        "number": number,
        "path": str(path),
        "params": params,
        "nets": nets,
        "body": body_text
    }

def run():
    con = init_db()
    cur = con.cursor()

    records = []
    for f in sorted(glob.glob(str(DATA_DIR / "*.xml"))):
        try:
            rec = parse_fb_xml(Path(f))
            # ulož do SQL
            cur.execute("INSERT INTO fb_blocks(name,title,number,path,body) VALUES(?,?,?,?,?)",
                        (rec["name"], rec["title"], rec["number"], rec["path"], rec["body"]))
            fb_id = cur.lastrowid
            for p in rec["params"]:
                cur.execute("INSERT INTO fb_params(fb_id,direction,name,datatype,comment) VALUES(?,?,?,?,?)",
                            (fb_id, p["direction"], p["name"], p["datatype"], p["comment"]))
            for n in rec["nets"]:
                cur.execute("INSERT INTO fb_networks(fb_id,net_no,code,comment) VALUES(?,?,?,?)",
                            (fb_id, n["net_no"], n["code"], n["comment"]))
            records.append({"fb_id": fb_id, "name": rec["name"], "body": rec["body"]})
        except Exception as e:
            print(f"[WARN] {f}: {e}")

    con.commit()

    # Embeddingy + FAISS
    if records:
        texts = [r["body"] for r in records]
        X = embed(texts)  # (N, 3072)
        np.save(FAISS_STORE_PATH, np.array([r["fb_id"] for r in records], dtype=np.int64))
        import faiss
        index = faiss.IndexFlatIP(X.shape[1])
        # normalizace pro cosine
        faiss.normalize_L2(X)
        index.add(X)
        faiss.write_index(index, str(FAISS_VEC_PATH))
        print(f"[OK] Ingest hotov: {len(records)} FB, index {FAISS_VEC_PATH.name}")
    else:
        print(f"[INFO] Nic k indexaci. Zkontroluj obsah {DATA_DIR} a formát XML (Network/Source).")

if __name__ == "__main__":
    run()
