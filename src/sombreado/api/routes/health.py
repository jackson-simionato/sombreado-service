from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from sombreado.api.deps import get_generation_store
from sombreado.store import GenerationStore

router = APIRouter()


@router.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready(
    store: Annotated[GenerationStore, Depends(get_generation_store)],
) -> dict[str, object]:
    """Prove the Generation Store is openable after migrate (current may be null)."""
    try:
        with store.connection() as connection:
            connection.execute("SELECT 1 FROM alembic_version LIMIT 1").fetchone()
        current = store.current_generation()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="generation store not ready") from exc
    return {"status": "ok", "currentGeneration": current}
