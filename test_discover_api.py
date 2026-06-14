import httpx
try:
    r = httpx.get("http://127.0.0.1:8000/api/discover", timeout=10)
    print("Status:", r.status_code)
    print("Response:", r.json())
except Exception as e:
    print("Error:", e)
