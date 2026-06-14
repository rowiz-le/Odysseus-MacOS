import sys
import os

from core.database import SessionLocal
from routes.model_routes import _probe_endpoint_catalog

try:
    models, meta = _probe_endpoint_catalog("http://localhost:11434/v1", None, 5)
    print("MODELS:", models)
except Exception as e:
    print("ERROR:", e)
