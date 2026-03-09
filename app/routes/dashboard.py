import asyncio

from fastapi import APIRouter, Request
from app.database import fetch_all, get_setting
from app.utils import safe_int

router = APIRouter()


@router.get("/")
async def dashboard(request: Request):
    projects, schedules, recent_executions, token_config, token_status = await asyncio.gather(
        fetch_all("SELECT * FROM projects ORDER BY created_at DESC"),
        fetch_all(
            """SELECT s.*, p.name as project_name, p.type as project_type
               FROM schedules s JOIN projects p ON s.project_id = p.id
               ORDER BY s.updated_at DESC"""
        ),
        fetch_all(
            """SELECT e.*, s.name as schedule_name, p.name as project_name
               FROM executions e
               JOIN schedules s ON e.schedule_id = s.id
               JOIN projects p ON s.project_id = p.id
               ORDER BY e.started_at DESC LIMIT 10"""
        ),
        get_setting("token_check_config"),
        get_setting("token_check_status"),
    )
    token_config = token_config or {}
    token_status = token_status or {}

    # 통계
    stats = {
        "total_projects": len(projects),
        "active_projects": sum(1 for p in projects if p["enabled"]),
        "running_count": sum(1 for s in schedules if s["status"] == "running"),
        "total_runs": sum(s["run_count"] for s in schedules),
        "session_usage": safe_int(token_status.get("current_session_percent")),
        "session_limit": safe_int(token_config.get("session_limit_percent"), 80),
        "weekly_usage": safe_int(token_status.get("weekly_limit_percent")),
        "weekly_limit": safe_int(token_config.get("weekly_limit_percent"), 70),
    }

    return request.app.state.templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "projects": projects,
            "schedules": schedules,
            "recent_executions": recent_executions,
            "stats": stats,
            "page": "dashboard",
        },
    )
