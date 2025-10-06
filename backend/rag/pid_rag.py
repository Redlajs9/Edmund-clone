import os
import io
import re
import json
import faiss
import numpy as np
from typing import List, Dict, Any, Optional
from pypdf import PdfReader
from openai import OpenAI

# OCR stack
from pdf2image import convert_from_path
import pytesseract
from PIL import Image, ImageOps, ImageFilter

# ======== Nastavení modelu a cest ========
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

def _unique(seq: List[str]) -> List[str]:
    return sorted(list(set(seq)))

class PIDRAG:
    """
    P&ID RAG s vylepšeným OCR:
    - PDF text (pypdf) + fallback OCR (Tesseract)
    - předzpracování obrazu: upscale, autokontrast, odšum, threshold
    - regex detekce tagů (Vxxx, Pxxx, TTxxx, PIxxx, FIxxx, LTxxx, 91201PU001 apod.)
    """

    def __init__(
        self,
        pids_dir: str = os.getenv("PIDS_DIR", "/app/data/pids"),
        index_path: str = os.getenv("PID_INDEX_PATH", "/app/data/pids/faiss.index"),
        store_path: str = os.getenv("PID_STORE_PATH", "/app/data/pids/store.npy"),
        meta_path: str = os.getenv("PID_META_PATH", "/app/data/pids/meta.json"),
        openai_api_key: str = os.getenv("OPENAI_API_KEY", ""),
        ocr_langs: str = os.getenv("PID_OCR_LANGS", "eng+ces+deu"),
        ocr_dpi: int = int(os.getenv("PID_OCR_DPI", "300")),
        ocr_enable: bool = os.getenv("PID_OCR_ENABLE", "true").lower() == "true",
        ocr_max_pages: Optional[int] = int(os.getenv("PID_OCR_MAX_PAGES", "0")) if os.getenv("PID_OCR_MAX_PAGES") else None,
        ocr_upscale: float = float(os.getenv("PID_OCR_UPSCALE", "1.8")),   # ~1.5–2.5 obvykle pomáhá
        ocr_threshold: int = int(os.getenv("PID_OCR_THRESHOLD", "180")),   # 0–255, vyšší = více bílého
        ocr_median: int = int(os.getenv("PID_OCR_MEDIAN", "3")),           # 0 = vypnuto; jinak velikost filtru (3/5)
    ):
        self.pids_dir = pids_dir
        self.index_path = index_path
        self.store_path = store_path
        self.meta_path = meta_path
        self.client = OpenAI(api_key=openai_api_key)
        self.index = None
        self.vectors = None
        self.meta: List[Dict[str, Any]] = []

        self.ocr_langs = ocr_langs
        self.ocr_dpi = ocr_dpi
        self.ocr_enable = ocr_enable
        self.ocr_max_pages = ocr_max_pages
        self.ocr_upscale = max(1.0, ocr_upscale)
        self.ocr_threshold = max(0, min(255, ocr_threshold))
        self.ocr_median = max(0, ocr_median)

    # ===== Embedding =====
    def _embed(self, texts: List[str]) -> np.ndarray:
        resp = self.client.embeddings.create(model=EMBED_MODEL, input=texts)
        vecs = [d.embedding for d in resp.data]
        return np.array(vecs, dtype="float32")

    # ===== Tagy =====
    def _extract_tags(self, text: str) -> List[str]:
        # rozšířený regex pro čísla + písmena + čísla (např. 91201PU001)
        patterns = [
            r"\bV-?\d{2,4}\b",                 # V102, V-102
            r"\bP-?\d{2,4}\b",                 # P301, P-301
            r"\bT[IT]C?-?\d{2,4}\b",           # TT101, TIC-201
            r"\bPI-?\d{2,4}\b",                # PI102
            r"\bFI-?\d{2,4}\b",                # FI302
            r"\bLT-?\d{2,4}\b",                # LT101
            r"\b[0-9]{4,6}[A-Z]{2,3}[0-9]{2,4}\b",  # 91201PU001 apod.
        ]
        tags: List[str] = []
        for pat in patterns:
            tags.extend(re.findall(pat, text, flags=re.IGNORECASE))
        norm = [t.upper().replace("--", "-") for t in tags]
        return _unique(norm)

    # ===== Předzpracování obrazu pro OCR =====
    def _preprocess_image(self, im: Image.Image) -> Image.Image:
        """
        Kroky:
        - převod do odstínů šedi,
        - upscale (bicubic),
        - autokontrast,
        - volitelně median filter na odšum,
        - pevný threshold do binární podoby.
        """
        # grayscale
        out = im.convert("L")

        # upscale
        if self.ocr_upscale and self.ocr_upscale > 1.0:
            w, h = out.size
            out = out.resize((int(w * self.ocr_upscale), int(h * self.ocr_upscale)), Image.BICUBIC)

        # autokontrast (zvedne separaci znak/pozadí)
        out = ImageOps.autocontrast(out)

        # volitelně odšum median filtrem
        if self.ocr_median and self.ocr_median >= 3 and self.ocr_median % 2 == 1:
            try:
                out = out.filter(ImageFilter.MedianFilter(self.ocr_median))
            except Exception:
                pass

        # threshold (binarizace)
        thr = self.ocr_threshold
        out = out.point(lambda x: 255 if x >= thr else 0).convert("L")

        return out

    def _tesseract_try(self, image: Image.Image) -> str:
        """
        Zkus více konfigurací Tesseractu – vezmi nejdelší (nejbohatší) čitelný výstup.
        """
        candidates = []
        configs = [
            "--oem 1 --psm 6",    # jeden blok textu
            "--oem 1 --psm 11",   # rozptýlený text
            "--oem 1 --psm 4",    # sloupec(y) textu
        ]
        for cfg in configs:
            try:
                txt = pytesseract.image_to_string(image, lang=self.ocr_langs, config=cfg)
                txt = " ".join(txt.split())
                if txt:
                    candidates.append(txt)
            except Exception:
                pass
        if not candidates:
            return ""
        # heuristika: vezmi nejdelší (typicky nejlepší pokrytí)
        return max(candidates, key=len)

    # ===== OCR jedné stránky =====
    def _ocr_text_from_page(self, pdf_path: str, page_index: int) -> str:
        # pdf2image indexuje od 1
        images = convert_from_path(pdf_path, dpi=self.ocr_dpi,
                                   first_page=page_index + 1,
                                   last_page=page_index + 1,
                                   fmt="png")
        texts: List[str] = []
        for im in images:
            # dvě cesty: (A) heavy preprocess, (B) jen grayscale (fallback)
            try:
                pre = self._preprocess_image(im)
                txtA = self._tesseract_try(pre)
            except Exception:
                txtA = ""

            try:
                gray = im.convert("L")
                txtB = self._tesseract_try(gray)
            except Exception:
                txtB = ""

            # vyber lepší
            chosen = txtA if len(txtA) >= len(txtB) else txtB
            texts.append(chosen)

        joined = " ".join(t for t in texts if t)
        return joined

    # ===== PDF loading =====
    def _load_pdf_pages(self, pdf_path: str) -> List[Dict[str, Any]]:
        pages = []
        with open(pdf_path, "rb") as f:
            reader = PdfReader(io.BytesIO(f.read()))

        for i, page in enumerate(reader.pages):
            try:
                raw = page.extract_text() or ""
            except Exception:
                raw = ""

            text = " ".join(raw.split())
            did_ocr = False

            if self.ocr_enable and (len(text) < 5):
                if self.ocr_max_pages is None or i < self.ocr_max_pages:
                    try:
                        ocr_text = self._ocr_text_from_page(pdf_path, i)
                        if len(ocr_text) >= 2:
                            text = ocr_text
                            did_ocr = True
                    except Exception:
                        pass

            tags = self._extract_tags(text) if text else []
            pages.append({
                "file": os.path.basename(pdf_path),
                "page": i + 1,
                "text": text,
                "tags": tags,
                "ocr": did_ocr,
            })
        return pages

    # ===== Indexace =====
    def reindex(self, force_ocr: bool = False) -> Dict[str, Any]:
        """
        Vytvoří embedding index pro všechny PDF v pids_dir.
        force_ocr=True → vynutí OCR i u textových PDF.
        """
        docs: List[Dict[str, Any]] = []
        for root, _, files in os.walk(self.pids_dir):
            for fn in files:
                if fn.lower().endswith(".pdf"):
                    full = os.path.join(root, fn)
                    if force_ocr:
                        prev_enable, prev_max = self.ocr_enable, self.ocr_max_pages
                        self.ocr_enable, self.ocr_max_pages = True, None
                        docs.extend(self._load_pdf_pages(full))
                        self.ocr_enable, self.ocr_max_pages = prev_enable, prev_max
                    else:
                        docs.extend(self._load_pdf_pages(full))

        if not docs:
            for p in [self.index_path, self.store_path, self.meta_path]:
                try:
                    os.remove(p)
                except:
                    pass
            self.index = None
            self.meta = []
            return {"pages_indexed": 0, "ocr_used_pages": 0}

        texts = [d["text"] if d["text"] else f"{d['file']} page {d['page']}" for d in docs]
        vecs = self._embed(texts)
        dim = vecs.shape[1]

        faiss.normalize_L2(vecs)
        index = faiss.IndexFlatIP(dim)
        index.add(vecs)

        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        faiss.write_index(index, self.index_path)
        np.save(self.store_path, vecs)
        with open(self.meta_path, "w", encoding="utf-8") as fw:
            json.dump(docs, fw, ensure_ascii=False, indent=2)

        self.index = index
        self.vectors = vecs
        self.meta = docs

        ocr_used = sum(1 for d in docs if d.get("ocr"))
        return {"pages_indexed": len(docs), "ocr_used_pages": ocr_used}

    # ===== Lazy load =====
    def _lazy_load(self):
        if self.index is None:
            if (os.path.exists(self.index_path)
                and os.path.exists(self.store_path)
                and os.path.exists(self.meta_path)):
                self.index = faiss.read_index(self.index_path)
                self.vectors = np.load(self.store_path)
                with open(self.meta_path, "r", encoding="utf-8") as fr:
                    self.meta = json.load(fr)
            else:
                self.index = None
                self.vectors = None
                self.meta = []

    # ===== Vyhledávání =====
    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        self._lazy_load()
        if not self.index or self.vectors is None or not len(self.meta):
            return []

        qvec = self._embed([query]).astype("float32")
        faiss.normalize_L2(qvec)
        scores, idxs = self.index.search(qvec, top_k)

        out = []
        for score, idx in zip(scores[0].tolist(), idxs[0].tolist()):
            if idx == -1:
                continue
            m = self.meta[idx]
            snippet = (m["text"][:220] + "…") if len(m["text"]) > 240 else m["text"]
            out.append({
                "file": m["file"],
                "page": m["page"],
                "score": float(score),
                "snippet": snippet,
                "tags": m.get("tags", []),
                "ocr": m.get("ocr", False),
            })
        return out

    # ===== Najdi tag =====
    def find_tag(self, tag: str) -> List[Dict[str, Any]]:
        self._lazy_load()
        if not self.meta:
            return []

        matches = []
        tag_upper = tag.strip().upper()
        for page in self.meta:
            if tag_upper in [t.upper() for t in page.get("tags", [])]:
                snippet = (page["text"][:220] + "…") if len(page["text"]) > 240 else page["text"]
                matches.append({
                    "file": page["file"],
                    "page": page["page"],
                    "snippet": snippet,
                    "ocr": page.get("ocr", False),
                    "tags": page.get("tags", []),
                })
        return matches
