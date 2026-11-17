"""Convenience runner script for AutoPost Nexus FastAPI server."""

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print(" AutoPost Nexus - Automated Multi-Platform Posting System")
    print(" Dxora Technologies Practical Assessment")
    print(" Server: http://127.0.0.1:8000")
    print(" Swagger UI: http://127.0.0.1:8000/docs")
    print(" ReDoc UI: http://127.0.0.1:8000/redoc")
    print(" Health Endpoint: http://127.0.0.1:8000/health")
    print("=" * 60)
    uvicorn.run("autopost_nexus.main:app", host="127.0.0.1", port=8000, reload=True)
