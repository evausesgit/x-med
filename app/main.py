"""Point d'entrée de l'API X-Med."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import digest, doctors, eval, me, saved_searches, search
from app.config import settings

app = FastAPI(title="X-Med API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    # En dev le front peut tourner sur un autre port localhost (3000, 3003…)
    allow_origin_regex=r"http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router, tags=["search"])
app.include_router(doctors.router, tags=["doctors"])
app.include_router(me.router, tags=["me"])
app.include_router(eval.router, tags=["eval"])
app.include_router(saved_searches.router, tags=["saved-searches"])
app.include_router(digest.router, tags=["digest"])


@app.get("/")
def root() -> dict:
    return {
        "name": "X-Med API",
        "status": "ok",
        "health": "/health",
        "docs": "/docs",
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
