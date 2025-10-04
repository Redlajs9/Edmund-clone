from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# dual import: lokálně (backend.api...) i v dockeru (api...)
try:
    from backend.api.routers import health, chat, readiness
except ImportError:
    from api.routers import health, chat, readiness

app = FastAPI(title="Edmund Chat API")

# CORS – povolíme všechny lokální originy (localhost/127.0.0.1 na libovolném portu)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(readiness.router)
