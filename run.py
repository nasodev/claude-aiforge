#!/usr/bin/env python3
"""AIForge - AI Workflow Manager"""
import os
import uvicorn

if __name__ == "__main__":
    os.makedirs("workspace/system", exist_ok=True)
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8010,
        reload=True,
        log_level="info",
    )
