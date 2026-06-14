import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
r = client.post("/api/model-endpoints", data={"base_url": "http://localhost:11434/v1"})
print("Status:", r.status_code)
print("JSON:", r.json())
