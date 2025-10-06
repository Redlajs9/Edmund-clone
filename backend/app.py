# backend/app.py
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# ==== Import routerů ====
# Použijeme vždy relativní importy, aby fungovalo spolehlivě jak v Dockeru, tak při lokálním běhu.
from .api.routers import (
    health,
    chat,
    readiness,
    preview,
    pids,
    logic,
    unified,
)

# ==== FastAPI app ====
app = FastAPI(title="Edmund Chat API")

# ==== CORS ====
# Povolit všechny lokální originy (localhost / 127.0.0.1 na libovolném portu)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==== Statické soubory ====
# ROOT = projektová složka (o úroveň výš nad 'backend')
BACKEND_DIR = Path(__file__).resolve().parent          # .../backend
ROOT_DIR = BACKEND_DIR.parent                          # projekt root
DATA_DIR = ROOT_DIR / "data"                           # .../data
PREVIEWS_DIR = DATA_DIR / "previews"                   # .../data/previews

# vytvoř složky, pokud chybí (bezpečné i pro read-only mount)
DATA_DIR.mkdir(parents=True, exist_ok=True)
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

# 1) /data/... (doporučeno pro FE – kompatibilní s relativními cestami "data/...")
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# 2) /previews/... (alias – pokud FE posílá rovnou tato URL)
app.mount("/previews", StaticFiles(directory=str(PREVIEWS_DIR)), name="previews")

# ==== Routers ====
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(readiness.router)
app.include_router(preview.router)  # dynamický fallback /preview/electrical
app.include_router(pids.router)
app.include_router(logic.router)
app.include_router(unified.router)
