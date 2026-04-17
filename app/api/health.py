from fastapi import APIRouter
from app.config import EXPORT_DIR, META_API_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {
        "ok": True,
        "meta_api_version": META_API_VERSION,
        "export_dir": str(EXPORT_DIR),
        "message": "Project structure bootstrap is working"
    }
