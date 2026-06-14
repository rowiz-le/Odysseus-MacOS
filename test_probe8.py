import sys
import asyncio
from core.database import SessionLocal, ModelEndpoint
import json

db = SessionLocal()
ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url.like('%11434%')).first()
print("Name:", ep.name)
print("Cached Models:", ep.cached_models)
if ep.cached_models:
    models = json.loads(ep.cached_models)
    print("Num Models:", len(models))
