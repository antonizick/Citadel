#!/usr/bin/env python3
"""Entry point for Nx-Citadel. Run: python run.py"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",  # uvicorn access logs — app uses its own handler
    )
