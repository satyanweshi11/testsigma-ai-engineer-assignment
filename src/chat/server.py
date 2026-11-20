"""Local web app to chat with the agent about the components.

    python -m uvicorn src.chat.server:app --port 8000
    # or:  python run.py chat

Serves a small chat UI at http://localhost:8000 and a POST /api/chat endpoint that
retrieves the relevant subgraph from Neo4j and has the LLM answer, grounded.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from neo4j import GraphDatabase

from src import config
from src.llm import get_client
from src.chat.agent import retrieve, answer

_INDEX = (Path(__file__).parent / "index.html").read_text()
_state: dict = {}


def _init():
    if "driver" not in _state:
        s = config.load()
        _state["settings"] = s
        _state["driver"] = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
        _state["llm"] = get_client()
    return _state


@asynccontextmanager
async def _lifespan(_app):
    # build the Neo4j driver + LLM client up front, not on the first request
    try:
        _init()
    except Exception as e:
        print(f"warmup deferred: {e}")
    yield


app = FastAPI(title="Blast Radius Assistant", lifespan=_lifespan)


class ChatIn(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index():
    return _INDEX


@app.get("/api/health")
def health():
    try:
        st = _init()
        with st["driver"].session() as se:
            n = se.run("MATCH (n) RETURN count(n) AS n").single()["n"]
        return {"ok": True, "nodes": n}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)


@app.post("/api/chat")
def chat(body: ChatIn):
    q = (body.question or "").strip()
    if not q:
        return JSONResponse({"error": "empty question"}, status_code=400)
    try:
        st = _init()
        with st["driver"].session() as se:
            context = retrieve(se, q)
        reply = answer(st["llm"], q, context)
        return {"answer": reply, "context": context}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
