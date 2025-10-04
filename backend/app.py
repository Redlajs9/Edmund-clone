# backend/app.py
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import routerů – pokusíme se načíst relativně (docker), jinak absolutně (lokální běh)
try:
    from backend.api.routers import health, chat, readiness, preview
except ImportError:
    from .api.routers import health, chat, readiness, preview

app = FastAPI(title="Edmund Chat API")

# CORS – povolíme všechny lokální originy (localhost/127.0.0.1 na libovolném portu)
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
ROOT_DIR    = BACKEND_DIR.parent                       # projekt root
DATA_DIR    = ROOT_DIR / "data"                         # .../data
PREVIEWS_DIR = DATA_DIR / "previews"                    # .../data/previews

# vytvoř složky, pokud chybí (nerozbije to read-only mount)
DATA_DIR.mkdir(parents=True, exist_ok=True)
PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

# 1) /data/... (doporučeno používat ve FE – kompatibilní s tvými relativními cestami "data/...")
app.mount("/data", StaticFiles(directory=str(DATA_DIR)), name="data")

# 2) /previews/... (alias – pokud by FE posílal rovnou tahle URL)
app.mount("/previews", StaticFiles(directory=str(PREVIEWS_DIR)), name="previews")

# ==== Routers ====
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(readiness.router)
app.include_router(preview.router)  # dynamický fallback /preview/electrical
