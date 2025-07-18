#auth_middleware.py
import os
import httpx
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.datastructures import MutableHeaders

USER_SERVICE_URL = os.getenv("USER_SERVICE_URL")

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        
        public_paths = ["/api/auth/login", "/api/auth/register"]
        
        if request.method in ("GET", "OPTIONS") or request.url.path in public_paths:
            return await call_next(request)

        session_id = request.cookies.get("session_id")
        print(f"Request received: {request.method} {request.url.path}")
        if not session_id:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        try:
            async with httpx.AsyncClient() as client:
                auth_url = f"{USER_SERVICE_URL}/api/auth/me"
                auth_resp = await client.get(auth_url, cookies={"session_id": session_id})

                if auth_resp.status_code != 200:
                    return JSONResponse(status_code=auth_resp.status_code, content=auth_resp.json())
                
                user_data = auth_resp.json()
                user_id = str(user_data.get("id"))

                new_headers = request.headers.mutablecopy()
                
                new_headers["X-User-Id"] = user_id
                request.scope["headers"] = new_headers.raw
                print("--- Modified Headers (new_headers) ---")
                print(new_headers)
                print("--------------------------------------")
        except httpx.RequestError:
            return JSONResponse(status_code=503, content={"detail": "User service is unavailable"})

        response = await call_next(request)
        return response