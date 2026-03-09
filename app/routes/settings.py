import asyncio

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.database import get_setting, update_setting

router = APIRouter(prefix="/settings")


@router.get("/")
async def settings_page(request: Request):
    token_config, token_status, log_config, log_status, global_setting = await asyncio.gather(
        get_setting("token_check_config"),
        get_setting("token_check_status"),
        get_setting("log_monitor_config"),
        get_setting("log_monitor_status"),
        get_setting("global"),
    )
    token_config = token_config or {}
    token_status = token_status or {}
    log_config = log_config or {}
    log_status = log_status or {}
    global_setting = global_setting or {}

    return request.app.state.templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "token_config": token_config,
            "token_status": token_status,
            "log_config": log_config,
            "log_status": log_status,
            "global_setting": global_setting,
            "page": "settings",
        },
    )


@router.post("/token_check")
async def update_token_check(
    enabled: str = Form("off"),
    interval_minutes: int = Form(60),
    session_limit_percent: int = Form(80),
    weekly_limit_percent: int = Form(70),
):
    await update_setting("token_check_config", {
        "enabled": enabled == "on",
        "interval_minutes": interval_minutes,
        "session_limit_percent": session_limit_percent,
        "weekly_limit_percent": weekly_limit_percent,
    })
    from app.services.scheduler import reload_all
    await reload_all()
    return RedirectResponse("/settings", status_code=303)


@router.post("/log_monitor")
async def update_log_monitor(
    enabled: str = Form("off"),
    interval_minutes: int = Form(10),
):
    await update_setting("log_monitor_config", {
        "enabled": enabled == "on",
        "interval_minutes": interval_minutes,
    })
    from app.services.scheduler import reload_all
    await reload_all()
    return RedirectResponse("/settings", status_code=303)


@router.post("/trigger/token_check")
async def trigger_token_check():
    from app.services.scheduler import _job_check_token
    await _job_check_token()
    return {"status": "ok", "job": "token_check"}


@router.post("/trigger/log_monitor")
async def trigger_log_monitor():
    from app.services.scheduler import _job_check_logs
    await _job_check_logs()
    return {"status": "ok", "job": "log_monitor"}


@router.post("/global")
async def update_global(
    auto_pause_on_limit: str = Form("off"),
    max_concurrent_executions: int = Form(3),
):
    await update_setting("global", {
        "auto_pause_on_limit": auto_pause_on_limit == "on",
        "max_concurrent_executions": max_concurrent_executions,
    })
    return RedirectResponse("/settings", status_code=303)
