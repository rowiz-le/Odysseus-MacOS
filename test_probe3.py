import sys
import os

from routes.model_routes import _probe_endpoint_standard

# Patch it locally to avoid DB
import core.database
class MockSessionLocal:
    def __enter__(self): return self
    def __exit__(self, *args): pass
core.database.SessionLocal = MockSessionLocal

try:
    # Use Gatecheap URL to see what it returns. Gatecheap is: https://gatecheap.io.vn/v1
    models = _probe_endpoint_standard("https://gatecheap.io.vn/v1", None, 5)
    print("GATECHEAP MODELS (no key):", len(models), models)
except Exception as e:
    print("ERROR Gatecheap:", e)

try:
    # Use localhost:11434 to see if anything is actually running
    models = _probe_endpoint_standard("http://localhost:11434/v1", None, 5)
    print("LOCALHOST MODELS:", len(models), models)
except Exception as e:
    print("ERROR localhost:", e)

