"""
Main FastAPI application entrypoint for Nigrani backend.
"""

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict

from backend.app.auth import get_current_user
from backend.app.db.models import User

app = FastAPI(title="Nigrani API", version="0.1.0")

api_v1_router = APIRouter(prefix="/api/v1")


class UserMeResponse(BaseModel):
    """Authenticated user profile response for /api/v1/me."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str


@api_v1_router.get("/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


@api_v1_router.get("/me", response_model=UserMeResponse)
def get_me(current_user: User = Depends(get_current_user)) -> dict[str, str]:
    """Return profile and role for the currently authenticated platform user."""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "role": current_user.role,
    }


app.include_router(api_v1_router)
