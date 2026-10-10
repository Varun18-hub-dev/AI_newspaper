"""FastAPI application factory with CORS middleware, lifespan handling, and route mounting."""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.logging import setup_logger

logger = setup_logger("fastapi_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown event handler."""
    logger.info("Initializing Personalized AI Newspaper REST API...")
    yield
    logger.info("Shutting down Personalized AI Newspaper REST API...")


def create_app() -> FastAPI:
    """Creates and configures the FastAPI application instance."""
    app = FastAPI(
        title="Personalized AI Newspaper API",
        description="REST API for multi-domain news discovery, story clustering, and run telemetry.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS configuration for Next.js frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "*",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount API routers
    app.include_router(router)

    @app.get("/")
    def root():
        return {
            "name": "Personalized AI Newspaper API",
            "version": "1.0.0",
            "docs_url": "/docs",
            "health_url": "/api/health",
        }

    return app


app = create_app()
