from core.database import SessionLocal, ModelEndpoint
db = SessionLocal()
ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url.like('%11434%')).first()
if ep:
    print("Name:", ep.name)
    print("Base URL:", ep.base_url)
    print("Cached Models:", ep.cached_models)
    print("Is Enabled:", ep.is_enabled)
else:
    print("Not found")
