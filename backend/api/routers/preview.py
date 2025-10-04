# backend/api/routers/preview.py
import os, hashlib
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from typing import Optional
from backend.services.tools import ELECTRICAL_DIR, ROOT
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

router = APIRouter(tags=["preview"])

CACHE_DIR = os.path.join(ROOT, "data", "previews")
os.makedirs(CACHE_DIR, exist_ok=True)

def _safe_join(base: str, rel: str) -> str:
    # zamezí ../ průnikům; povolujeme jen cesty relativní vůči ROOT
    p = os.path.normpath(os.path.join(ROOT, rel))
    if not p.startswith(ROOT):
        raise HTTPException(status_code=400, detail="Invalid path")
    return p

@router.get("/preview/electrical")
def preview_electrical(
    file: str = Query(..., description="Relativní cesta k PDF (např. data/electrical/Schrank1.pdf)"),
    page: int = Query(1, ge=1),
    tag: Optional[str] = Query(None, description="Volitelně zvýrazní výskyt tagu"),
    scale: float = Query(2.0, ge=0.5, le=4.0, description="Zoom (2.0=200%)"),
    fmt: str = Query("png", pattern="^(png|jpg|jpeg)$")
):
    if fitz is None:
        raise HTTPException(status_code=500, detail="PyMuPDF (pymupdf) není nainstalováno")

    pdf_path = _safe_join(ROOT, file)
    if not os.path.isfile(pdf_path) or not pdf_path.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Soubor nenalezen")

    # cache klíč
    key_src = f"{pdf_path}|p{page}|tag:{tag or ''}|s{scale}|{fmt}"
    key = hashlib.sha1(key_src.encode("utf-8")).hexdigest()
    out_path = os.path.join(CACHE_DIR, f"{key}.{ 'jpg' if fmt in ('jpg','jpeg') else 'png'}")
    if os.path.exists(out_path):
        return FileResponse(out_path, media_type=f"image/{'jpeg' if fmt!='png' else 'png'}")

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF chyba: {e}")

    if page < 1 or page > len(doc):
        doc.close()
        raise HTTPException(status_code=400, detail=f"Strana mimo rozsah 1..{len(doc)}")

    try:
        pg = doc.load_page(page - 1)
        # vykreslení
        mat = fitz.Matrix(scale, scale)
        pix = pg.get_pixmap(matrix=mat, alpha=False)

        # zvýraznění tagu (pokud je)
        if tag:
            # hledání obdélníků – case-insensitive
            rects = pg.search_for(tag, flags=fitz.TEXT_DEHYPHENATE | fitz.TEXT_PRESERVE_LIGATURES)
            if rects:
                # vytvoříme dočasnou anotaci, ať ji umí pixmap zohlednit
                for r in rects:
                    annot = pg.add_rect_annot(r)
                    annot.set_colors(stroke=(1, 0, 0))  # červená
                    annot.set_border(width=2)
                    annot.update()
                # znovu vyrenderujeme stránku se zvýrazněním
                pix = pg.get_pixmap(matrix=mat, alpha=False)
                # uklid: odstraníme anotace (neukládáme do PDF, jsou jen v paměti)
                for a in pg.annots() or []:
                    pg.delete_annot(a)

        # uložení
        if fmt == "png":
            pix.save(out_path, output="png")
        else:
            # PyMuPDF ukládá do PNG; pro JPG použijeme PIL, když je k dispozici
            try:
                from PIL import Image
                import io
                buf = pix.tobytes("png")
                im = Image.open(io.BytesIO(buf)).convert("RGB")
                im.save(out_path, format="JPEG", quality=90)
            except Exception:
                pix.save(out_path, output="png")
                out_path = out_path.rsplit(".",1)[0] + ".png"

    finally:
        doc.close()

    return FileResponse(out_path, media_type=f"image/{'jpeg' if fmt!='png' else 'png'}")
