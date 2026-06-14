import sys
import asyncio
from core.database import SessionLocal, ModelEndpoint
from routes.model_routes import create_model_endpoint
from fastapi import Request

async def main():
    db = SessionLocal()
    ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url.like('%11434%')).first()
    class App:
        state = type('State', (), {'db': db})
    class MockReq:
        @property
        def app(self): return App()
            
    await create_model_endpoint(MockReq(), base_url="http://localhost:11434/v1", name="", provider="")
    
    db.refresh(ep)
    print("Cached Models:", ep.cached_models)

asyncio.run(main())
