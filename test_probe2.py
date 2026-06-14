import sys
import os

from routes.model_routes import _probe_endpoint_standard

try:
    models = _probe_endpoint_standard("http://localhost:11434/v1", None, 5)
    print("MODELS:", models)
except Exception as e:
    print("ERROR:", e)
