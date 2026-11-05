from fastapi import APIRouter, FastAPI

app = FastAPI(title="Nigrani API", version="0.1.0")

api_v1_router = APIRouter(prefix="/api/v1")


@api_v1_router.get("/health")
def health_check():
    return {"status": "ok"}


app.include_router(api_v1_router)
