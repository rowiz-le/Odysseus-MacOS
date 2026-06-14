import sys
import asyncio
from core.database import SessionLocal, ModelEndpoint
from routes.model_routes import create_model_endpoint

async def main():
    db = SessionLocal()
    ep = db.query(ModelEndpoint).filter(ModelEndpoint.base_url.like('%11434%')).first()
    print("EP before:", ep.cached_models)
    
    from fastapi import Request
    class MockReq:
        @property
        def app(self):
            class App:
                state = type('State', (), {'db': db})
            return App()
            
    await create_model_endpoint(MockReq(), base_url="http://localhost:11434/v1", name="", provider="")
    print("EP after:", ep.cached_models)

asyncio.run(main())
