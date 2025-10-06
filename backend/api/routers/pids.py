from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Dict, Any
from backend.rag.pid_rag import PIDRAG

router = APIRouter(prefix="/pids", tags=["pids"])
rag = PIDRAG()

class SearchBody(BaseModel):
    query: str = Field(..., min_length=2)
    top_k: int = 5

class TagBody(BaseModel):
    tag: str = Field(..., min_length=1)

class ReindexBody(BaseModel):
    force_ocr: bool = False

@router.post("/reindex")
def reindex(body: ReindexBody = ReindexBody()) -> Dict[str, Any]:
    try:
        stats = rag.reindex(force_ocr=bool(body.force_ocr))
        return {"status": "ok", **stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search")
def search(body: SearchBody) -> Dict[str, Any]:
    try:
        results = rag.search(body.query, body.top_k)
        return {"status": "ok", "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/find_tag")
def find_tag(body: TagBody) -> Dict[str, Any]:
    try:
        hits = rag.find_tag(body.tag)
        return {"status": "ok", "matches": hits}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/ocr_preview")
def ocr_preview(page: int = Query(1, ge=1)) -> Dict[str, Any]:
    """
    Vrátí čistý OCR text z vybrané stránky PID PDF (pro debug).
    """
    rag._lazy_load()
    if not rag.meta:
        return {"status": "empty_index"}

    # omez na existující rozsah
    if page > len(rag.meta):
        page = len(rag.meta)

    text = rag.meta[page - 1].get("text", "")
    ocr_flag = rag.meta[page - 1].get("ocr", False)
    tags = rag.meta[page - 1].get("tags", [])
    return {
        "status": "ok",
        "page": page,
        "ocr": ocr_flag,
        "tags": tags,
        "text_excerpt": text[:1500]  # zkrácený text pro přehlednost
    }
