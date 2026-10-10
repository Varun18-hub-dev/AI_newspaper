"""CLI runner script for the Personalized AI Newspaper FastAPI backend.

Usage:
    python scripts/run_api.py [--host HOST] [--port PORT] [--reload]
"""

import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Run the Personalized AI Newspaper API server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code change")
    args = parser.parse_args()

    print(f"Starting Personalized AI Newspaper API on http://{args.host}:{args.port}")
    print(f"Interactive OpenAPI Documentation: http://{args.host}:{args.port}/docs")
    print(f"Health Check: http://{args.host}:{args.port}/api/health")

    uvicorn.run(
        "app.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
