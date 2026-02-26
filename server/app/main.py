from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import create_db_and_tables
from app.routers import health, ollama, agents, teams, runs, tools, exports, snapshot


def create_app() -> FastAPI:
    app = FastAPI(title='Agentora')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.on_event('startup')
    def startup():
        create_db_and_tables()

    app.include_router(health.router)
    app.include_router(ollama.router)
    app.include_router(agents.router)
    app.include_router(teams.router)
    app.include_router(runs.router)
    app.include_router(tools.router)
    app.include_router(exports.router)
    app.include_router(snapshot.router)
    return app


app = create_app()
