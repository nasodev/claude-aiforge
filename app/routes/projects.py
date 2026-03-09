import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Form
from fastapi.responses import RedirectResponse

from app.database import fetch_all, fetch_one, execute

router = APIRouter(prefix="/projects")


@router.get("/")
async def list_projects(request: Request):
    projects = await fetch_all(
        """SELECT p.*, 
              (SELECT COUNT(*) FROM schedules WHERE project_id = p.id) as schedule_count,
              (SELECT COUNT(*) FROM schedules WHERE project_id = p.id AND status = 'running') as running_count
           FROM projects p ORDER BY p.created_at DESC"""
    )
    return request.app.state.templates.TemplateResponse(
        "projects.html",
        {"request": request, "projects": projects, "page": "projects"},
    )


@router.get("/new")
async def new_project_form(request: Request):
    return request.app.state.templates.TemplateResponse(
        "project_form.html",
        {"request": request, "project": None, "page": "projects"},
    )


@router.get("/{project_id}/edit")
async def edit_project_form(request: Request, project_id: str):
    project = await fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if not project:
        return RedirectResponse("/projects", status_code=303)
    return request.app.state.templates.TemplateResponse(
        "project_form.html",
        {"request": request, "project": project, "page": "projects"},
    )


@router.post("/create")
async def create_project(
    request: Request,
    name: str = Form(...),
    type: str = Form(...),
    description: str = Form(""),
    jira_project: str = Form(""),
    jira_label: str = Form(""),
    jira_status: str = Form(""),
):
    project_id = str(uuid.uuid4())
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    await execute(
        """INSERT INTO projects (id, name, type, description, enabled, jira_project, jira_label, jira_status, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
        (project_id, name, type, description,
         jira_project or None, jira_label or None, jira_status or None,
         now, now),
    )
    return RedirectResponse(f"/projects", status_code=303)


@router.post("/{project_id}/update")
async def update_project(
    project_id: str,
    name: str = Form(...),
    type: str = Form(...),
    description: str = Form(""),
    jira_project: str = Form(""),
    jira_label: str = Form(""),
    jira_status: str = Form(""),
):
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    await execute(
        """UPDATE projects 
           SET name=?, type=?, description=?, jira_project=?, jira_label=?, jira_status=?, updated_at=?
           WHERE id=?""",
        (name, type, description,
         jira_project or None, jira_label or None, jira_status or None,
         now, project_id),
    )
    return RedirectResponse("/projects", status_code=303)


@router.post("/{project_id}/toggle")
async def toggle_project(project_id: str):
    project = await fetch_one("SELECT enabled FROM projects WHERE id = ?", (project_id,))
    if project:
        new_val = 0 if project["enabled"] else 1
        await execute(
            "UPDATE projects SET enabled = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime') WHERE id = ?",
            (new_val, project_id),
        )
        # 스케줄러 재로드
        from app.services.scheduler import reload_all
        await reload_all()
    return RedirectResponse("/projects", status_code=303)


@router.post("/{project_id}/delete")
async def delete_project(project_id: str):
    await execute("DELETE FROM projects WHERE id = ?", (project_id,))
    from app.services.scheduler import reload_all
    await reload_all()
    return RedirectResponse("/projects", status_code=303)
