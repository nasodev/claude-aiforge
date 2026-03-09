import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/schedules")


@router.get("/")
async def list_schedules(request: Request):
    schedules = await fetch_all(
        """SELECT s.*, p.name as project_name, p.type as project_type
           FROM schedules s JOIN projects p ON s.project_id = p.id
           ORDER BY s.created_at DESC"""
    )
    return request.app.state.templates.TemplateResponse(
        "schedules.html",
        {"request": request, "schedules": schedules, "page": "schedules"},
    )


@router.get("/new")
async def new_schedule_form(request: Request, project_id: str = ""):
    projects = await fetch_all("SELECT id, name, type FROM projects ORDER BY name")
    return request.app.state.templates.TemplateResponse(
        "schedule_form.html",
        {"request": request, "schedule": None, "projects": projects,
         "selected_project_id": project_id, "page": "schedules"},
    )


@router.get("/{schedule_id}/edit")
async def edit_schedule_form(request: Request, schedule_id: str):
    schedule = await fetch_one("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
    projects = await fetch_all("SELECT id, name, type FROM projects ORDER BY name")
    if not schedule:
        return RedirectResponse("/schedules", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "schedule_form.html",
        {"request": request, "schedule": schedule, "projects": projects,
         "selected_project_id": "", "page": "schedules"},
    )


@router.post("/create")
async def create_schedule(
    project_id: str = Form(...),
    name: str = Form(""),
    cron_expr: str = Form(...),
    work_dir: str = Form(...),
    prompt_template: str = Form(...),
):
    schedule_id = str(uuid.uuid4())
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    await execute(
        """INSERT INTO schedules (id, project_id, name, cron_expr, work_dir, prompt_template, enabled, status, run_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 1, 'idle', 0, ?, ?)""",
        (schedule_id, project_id, name or None, cron_expr, work_dir, prompt_template, now, now),
    )

    # 스케줄러에 등록
    from app.services.scheduler import reload_all
    await reload_all()

    return RedirectResponse("/schedules", status_code=303)


@router.post("/{schedule_id}/update")
async def update_schedule(
    schedule_id: str,
    project_id: str = Form(...),
    name: str = Form(""),
    cron_expr: str = Form(...),
    work_dir: str = Form(...),
    prompt_template: str = Form(...),
):
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    await execute(
        """UPDATE schedules 
           SET project_id=?, name=?, cron_expr=?, work_dir=?, prompt_template=?, updated_at=?
           WHERE id=?""",
        (project_id, name or None, cron_expr, work_dir, prompt_template, now, schedule_id),
    )
    from app.services.scheduler import reload_all
    await reload_all()
    return RedirectResponse("/schedules", status_code=303)


@router.post("/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str):
    sched = await fetch_one("SELECT enabled FROM schedules WHERE id = ?", (schedule_id,))
    if sched:
        new_val = 0 if sched["enabled"] else 1
        await execute(
            "UPDATE schedules SET enabled=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?",
            (new_val, schedule_id),
        )
        from app.services.scheduler import reload_all
        await reload_all()
    return RedirectResponse("/schedules", status_code=303)


@router.post("/{schedule_id}/run")
async def run_now(schedule_id: str):
    """수동 즉시 실행"""
    from app.services.scheduler import _job_run_schedule
    await _job_run_schedule(schedule_id)
    return RedirectResponse("/schedules", status_code=303)


@router.post("/{schedule_id}/delete")
async def delete_schedule(schedule_id: str):
    await execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    from app.services.scheduler import reload_all
    await reload_all()
    return RedirectResponse("/schedules", status_code=303)
