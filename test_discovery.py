import sys
from src.model_discovery import ModelDiscovery

d = ModelDiscovery("localhost")
res = d.discover_models()
print(res)
