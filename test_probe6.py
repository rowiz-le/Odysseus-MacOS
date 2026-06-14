import httpx
r = httpx.get("http://localhost:11434/v1/models")
print(r.status_code)
print(r.json())
