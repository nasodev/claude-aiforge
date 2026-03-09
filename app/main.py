import logging
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import init_db
from app.services.scheduler import init_scheduler
from app.routes import dashboard, projects, schedules, executions, settings, logs, templates

# ─── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("aiforge.log"),
    ],
)
logger = logging.getLogger("aiforge")

BASE_DIR = Path(__file__).parent


# ─── Lifespan ─────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("AIForge starting up...")
    await init_db()
    await init_scheduler()
    logger.info("AIForge ready")
    yield
    # Shutdown
    from app.services.scheduler import scheduler
    scheduler.shutdown(wait=False)
    logger.info("AIForge shut down")


# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="AIForge", version="0.1.0", lifespan=lifespan)

# Static files & Templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.state.templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Routes
app.include_router(dashboard.router)
app.include_router(projects.router)
app.include_router(schedules.router)
app.include_router(executions.router)
app.include_router(settings.router)
app.include_router(logs.router)
app.include_router(templates.router)
