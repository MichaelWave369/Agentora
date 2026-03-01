from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import health, ollama, agents, teams, runs, tools, exports, snapshot
from app.routers import marketplace, multimodal, voice, analytics, integrations, lan, studio, band, arena, gathering, legacy, cosmos, open_cosmos, garden, world_garden, capsules, workers, memory, team, actions, workflows


def create_app() -> FastAPI:
    app = FastAPI(title='Agentora v0.9.5 — Desktop Actions & Safe Automation')
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    @app.on_event('startup')
    def startup():
        init_db()

    app.include_router(health.router)
    app.include_router(ollama.router)
    app.include_router(agents.router)
    app.include_router(teams.router)
    app.include_router(runs.router)
    app.include_router(tools.router)
    app.include_router(exports.router)
    app.include_router(snapshot.router)
    app.include_router(marketplace.router)
    app.include_router(multimodal.router)
    app.include_router(voice.router)
    app.include_router(analytics.router)
    app.include_router(integrations.router)
    app.include_router(lan.router)
    app.include_router(studio.router)
    app.include_router(band.router)
    app.include_router(arena.router)
    app.include_router(gathering.router)
    app.include_router(legacy.router)
    app.include_router(cosmos.router)
    app.include_router(open_cosmos.router)
    app.include_router(garden.router)
    app.include_router(world_garden.router)
    app.include_router(capsules.router)
    app.include_router(workers.router)
    app.include_router(workers.worker_router)
    app.include_router(memory.router)
    app.include_router(team.router)
    app.include_router(actions.router)
    app.include_router(workflows.router)
    return app


app = create_app()
