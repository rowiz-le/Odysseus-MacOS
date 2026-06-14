import sys
import asyncio
from core.database import SessionLocal, ModelEndpoint
from routes.model_routes import setup_model_routes
from fastapi import FastAPI, Request

app = FastAPI()
db = SessionLocal()
ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url.like('%11434%')).first()
print("Before:", ep.cached_models)

app.state.db = db
# We don't need to actually call the endpoint via testclient if we can just find the function.
