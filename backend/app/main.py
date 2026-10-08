from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import analyzer, db, pipeline


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    db.fail_stale()
    yield


app = FastAPI(title="Debt Detector", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalysisIn(BaseModel):
    repo_url: str


@app.post("/api/analyses", status_code=202)
def create_analysis(body: AnalysisIn, bg: BackgroundTasks):
    try:
        url = analyzer.validate_url(body.repo_url)
    except ValueError as e:
        raise HTTPException(422, str(e))
    aid = db.create(url)
    bg.add_task(pipeline.run, aid, url)
    return {"id": aid}


@app.get("/api/analyses")
def list_analyses():
    return db.list_all()


@app.get("/api/analyses/{aid}")
def get_analysis(aid: str):
    row = db.get(aid)
    if not row:
        raise HTTPException(404, "Análisis no encontrado")
    return row
