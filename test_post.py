import sys
import httpx

r = httpx.post(
    "http://127.0.0.1:8000/api/model-endpoints",
    data={"base_url": "http://localhost:11434/v1"},
    timeout=5
)
print("Status:", r.status_code)
print("Text:", r.text)
