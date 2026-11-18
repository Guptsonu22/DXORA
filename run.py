"""Convenience runner script for AutoPost Nexus FastAPI server."""

import uvicorn

if __name__ == "__main__":
    print("=" * 60)
    print(" AutoPost Nexus - Automated Multi-Platform Posting System")
    print(" Dxora Technologies Practical Assessment")
    print(" Server: http://127.0.0.1:4000")
    print(" Swagger UI: http://127.0.0.1:4000/docs")
    print(" ReDoc UI: http://127.0.0.1:4000/redoc")
    print(" Health Endpoint: http://127.0.0.1:4000/health")
    print("=" * 60)
    uvicorn.run("app.main:app", host="0.0.0.0", port=4000, reload=True)
