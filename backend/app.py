from fastapi import FastAPI
from api.routers import health, chat, readiness

app = FastAPI(title="Edmund Chat API")
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(readiness.router)
