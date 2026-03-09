import logging
import psutil
from datetime import datetime

from app.database import fetch_all, execute

logger = logging.getLogger("aiforge.log_checker")


async def check_running_executions():
    """
    실행 중인 execution들의 상태를 확인.
    1. PID가 살아있는지 체크
    2. PID가 죽었으면 claude 로컬 로그를 파싱해서 결과 판단
    """
    running = await fetch_all(
        "SELECT id, pid, schedule_id, started_at, log_path FROM executions WHERE status = 'running'"
    )

    if not running:
        logger.debug("No running executions to check")
        return

    logger.info(f"Checking {len(running)} running executions")

    for exec_row in running:
        exec_id = exec_row["id"]
        pid = exec_row["pid"]
        schedule_id = exec_row["schedule_id"]
        started_at = exec_row["started_at"]

        # PID 체크 — 프로세스가 존재하고 실제 claude 프로세스인지 확인
        if pid and _is_claude_process(pid):
            logger.debug(f"Execution {exec_id} (PID={pid}) still running")
            continue

        # PID가 죽었음 → 완료 판단
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        duration = _calc_duration(started_at, now)

        # claude 로컬 로그 파싱으로 성공/실패 판단
        result = await _parse_claude_log(exec_row.get("log_path"))

        if result["success"]:
            await execute(
                """UPDATE executions 
                   SET status = 'success', finished_at = ?, duration_seconds = ?, result_summary = ?
                   WHERE id = ?""",
                (now, duration, result.get("summary", ""), exec_id),
            )
            logger.info(f"Execution {exec_id} completed successfully ({duration}s)")
        else:
            await execute(
                """UPDATE executions 
                   SET status = 'error', finished_at = ?, duration_seconds = ?, error_message = ?
                   WHERE id = ?""",
                (now, duration, result.get("error", "Process ended unexpectedly"), exec_id),
            )
            logger.warning(f"Execution {exec_id} failed ({duration}s)")

        # schedule 상태를 idle로 복구
        # 같은 schedule에 다른 running execution이 있는지 확인
        still_running = await fetch_all(
            "SELECT id FROM executions WHERE schedule_id = ? AND status = 'running' AND id != ?",
            (schedule_id, exec_id),
        )
        if not still_running:
            await execute(
                "UPDATE schedules SET status = 'idle', updated_at = ? WHERE id = ?",
                (now, schedule_id),
            )


async def _parse_claude_log(log_path: str | None) -> dict:
    """
    claude 로컬 로그 파일을 파싱해서 실행 결과 판단.
    
    TODO: 실제 claude 로그 경로와 포맷에 맞게 수정 필요.
    ~/.claude/logs/ 하위를 확인하거나,
    claude CLI의 종료 코드를 기반으로 판단.
    """
    if not log_path:
        # 로그 경로가 없으면 PID 종료 = 성공으로 간주
        return {"success": True, "summary": "Process completed (no log path)"}

    try:
        with open(log_path, "r") as f:
            content = f.read()

        # 에러 패턴 체크
        error_patterns = ["Error:", "error:", "FAILED", "Exception"]
        for pattern in error_patterns:
            if pattern in content:
                return {"success": False, "error": f"Found error pattern: {pattern}"}

        # 마지막 몇 줄을 summary로
        lines = content.strip().split("\n")
        summary = "\n".join(lines[-3:]) if len(lines) > 3 else content
        return {"success": True, "summary": summary[:500]}

    except FileNotFoundError:
        return {"success": True, "summary": "Log file not found, assuming success"}
    except Exception as e:
        return {"success": False, "error": f"Failed to parse log: {e}"}


def _is_claude_process(pid: int) -> bool:
    """PID가 존재하고 실제 claude 프로세스인지 확인 (PID 재사용 방지)"""
    try:
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
        return "claude" in cmdline
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def _calc_duration(started: str, finished: str) -> int:
    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        s = datetime.strptime(started, fmt)
        f = datetime.strptime(finished, fmt)
        return int((f - s).total_seconds())
    except Exception:
        return 0
