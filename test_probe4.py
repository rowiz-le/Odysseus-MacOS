from routes.model_routes import _probe_endpoint_catalog
import sys

models, meta = _probe_endpoint_catalog("http://localhost:11434/v1", None, timeout=5.0)
print("Models:", models)
print("Meta:", meta)
