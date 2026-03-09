from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from app.database import fetch_all, execute

router = APIRouter(prefix="/executions")


@router.get("/")
async def list_executions(request: Request, status: str = "", project: str = ""):
    where_clauses = []
    params = []

    if status:
        where_clauses.append("e.status = ?")
        params.append(status)
    if project:
        where_clauses.append("p.name = ?")
        params.append(project)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    executions = await fetch_all(
        f"""SELECT e.*, s.name as schedule_name, p.name as project_name, p.type as project_type
            FROM executions e
            JOIN schedules s ON e.schedule_id = s.id
            JOIN projects p ON s.project_id = p.id
            {where_sql}
            ORDER BY e.started_at DESC
            LIMIT 100""",
        tuple(params),
    )

    # 필터용 프로젝트 목록
    projects = await fetch_all("SELECT DISTINCT name FROM projects ORDER BY name")

    return request.app.state.templates.TemplateResponse(
        "executions.html",
        {
            "request": request,
            "executions": executions,
            "projects": projects,
            "filter_status": status,
            "filter_project": project,
            "page": "executions",
        },
    )


@router.post("/clear")
async def clear_executions(request: Request):
    """실행 이력 초기화 (running 상태 제외)"""
    await execute("DELETE FROM executions WHERE status != 'running'")
    return RedirectResponse(url="/executions", status_code=303)
