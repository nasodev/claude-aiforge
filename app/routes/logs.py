import asyncio
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

logger = logging.getLogger("aiforge.logs")

router = APIRouter(prefix="/logs")

# 기본값
DEFAULT_LOG_DIR = str(Path.home() / "dev/claude/claude-code-log")
LOG_OUTPUT_PATH = str(Path.home() / ".claude/projects/index.html")
UV_BIN = shutil.which("uv") or str(Path.home() / ".local/bin/uv")


@router.get("/")
async def logs_page(request: Request):
    return request.app.state.templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "page": "logs",
            "default_log_dir": DEFAULT_LOG_DIR,
        },
    )


@router.post("/generate")
async def generate_logs(
    request: Request,
    log_dir: str = Form(...),
    from_date: str = Form(...),
    to_date: str = Form(""),
):
    """claude-code-log 실행 후 결과 HTML 경로 반환"""
    work_dir = log_dir.strip() or DEFAULT_LOG_DIR
    if not Path(work_dir).is_dir():
        return JSONResponse(
            {"success": False, "error": f"폴더를 찾을 수 없습니다: {work_dir}"},
            status_code=400,
        )

    cmd = [UV_BIN, "run", "claude-code-log", "--from-date", from_date]
    if to_date.strip():
        cmd += ["--to-date", to_date.strip()]

    logger.info("Running: %s in %s", " ".join(cmd), work_dir)

    try:
        env = os.environ.copy()
        env["PATH"] = str(Path.home() / ".local/bin") + ":" + env.get("PATH", "")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        output = stdout.decode() + stderr.decode()
        logger.info("claude-code-log output: %s", output)

        if proc.returncode != 0:
            return JSONResponse(
                {"success": False, "error": output},
                status_code=400,
            )

        return JSONResponse({"success": True, "html_path": LOG_OUTPUT_PATH, "output": output})

    except asyncio.TimeoutError:
        return JSONResponse(
            {"success": False, "error": "Command timed out (120s)"},
            status_code=408,
        )
    except Exception as e:
        logger.exception("Failed to run claude-code-log")
        return JSONResponse(
            {"success": False, "error": str(e)},
            status_code=500,
        )


PROJECTS_DIR = Path.home() / ".claude/projects"


@router.get("/view/{file_path:path}")
async def view_log_file(file_path: str):
    """~/.claude/projects/ 하위 HTML 파일 서빙 (상대경로 링크 지원)"""
    target = (PROJECTS_DIR / file_path).resolve()
    # 디렉토리 탈출 방지
    if not str(target).startswith(str(PROJECTS_DIR) + os.sep):
        return HTMLResponse("접근 불가", status_code=403)
    if not target.exists() or not target.suffix == ".html":
        return HTMLResponse("<h3>파일을 찾을 수 없습니다.</h3>", status_code=404)
    return HTMLResponse(target.read_text(encoding="utf-8"))


@router.get("/view")
async def view_log_html():
    """index.html 서빙"""
    path = Path(LOG_OUTPUT_PATH)
    if not path.exists():
        return HTMLResponse("<h3>로그 파일이 아직 생성되지 않았습니다.</h3>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))
