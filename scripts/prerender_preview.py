# scripts/prerender_previews.py
import os, sys
from typing import Optional
import fitz  # PyMuPDF

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ELEC = os.path.join(ROOT, "data", "electrical")
OUT  = os.path.join(ROOT, "data", "previews")

def out_path_for(pdf_rel: str, page: int) -> str:
    """
    data/electrical/Foo/Doc.pdf + page -> data/previews/Foo/Doc_p0001.jpg
    """
    rel_no_root = os.path.relpath(pdf_rel, os.path.join(ROOT, "data", "electrical"))
    base, _ = os.path.splitext(rel_no_root)
    out_rel = os.path.join(OUT, base + f"_p{page:04d}.jpg")
    os.makedirs(os.path.dirname(out_rel), exist_ok=True)
    return out_rel

def render_pdf(pdf_path: str, scale: float = 2.0, quality: int = 85,
               max_pages: Optional[int] = None) -> int:
    doc = fitz.open(pdf_path)
    pages = range(1, min(len(doc), max_pages) + 1) if max_pages else range(1, len(doc) + 1)
    cnt = 0
    for p in pages:
        pg = doc.load_page(p - 1)
        pix = pg.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        outp = out_path_for(pdf_path, p)
        # ulož JPEG
        pix.save(outp, jpg_quality=quality)
        cnt += 1
    doc.close()
    return cnt

def main():
    scale = float(os.getenv("PREVIEW_SCALE", "2.0"))
    quality = int(os.getenv("PREVIEW_JPG_QUALITY", "85"))
    max_pages = int(os.getenv("PREVIEW_MAX_PAGES", "0")) or None

    total = 0
    for root, _, files in os.walk(ELEC):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                pdf = os.path.join(root, fn)
                try:
                    done = render_pdf(pdf, scale=scale, quality=quality, max_pages=max_pages)
                    print(f"[OK] {pdf} -> {done} pages")
                    total += done
                except Exception as e:
                    print(f"[ERR] {pdf}: {e}", file=sys.stderr)
    print(f"Done. Rendered {total} pages to {OUT}")

if __name__ == "__main__":
    main()
