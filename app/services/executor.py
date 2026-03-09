import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from app.database import execute, fetch_one


def _clean_env() -> dict:
    """CLAUDECODE 환경변수를 제거한 env dict 반환 (중첩 실행 방지 우회)"""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env

logger = logging.getLogger("aiforge.executor")


# ─── 모드 1: Fire-and-Forget (프로젝트 작업용) ─────────────────────────

async def run_claude_async(
    schedule_id: str,
    work_dir: str,
    prompt: str,
    issue_key: str | None = None,
) -> str:
    """
    claude CLI를 fire-and-forget으로 실행.
    PID와 실행 정보를 executions에 기록하고 즉시 반환.
    수십 분 걸릴 수 있는 프로젝트 개발 작업용.
    """
    execution_id = str(uuid.uuid4())
    command = f'claude --dangerously-skip-permissions --chrome -p "{prompt}"'
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    logger.info(f"[async] Executing: cd {work_dir} && {command}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--dangerously-skip-permissions", "--chrome", "-p", prompt,
            cwd=work_dir,
            env=_clean_env(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        await execute(
            """INSERT INTO executions 
               (id, schedule_id, pid, status, command, work_dir, issue_key, started_at)
               VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
            (execution_id, schedule_id, proc.pid, command, work_dir, issue_key, now),
        )

        await execute(
            """UPDATE schedules 
               SET status = 'running', 
                   last_run_at = ?,
                   run_count = run_count + 1,
                   updated_at = ?
               WHERE id = ?""",
            (now, now, schedule_id),
        )

        logger.info(f"[async] Started execution {execution_id}, PID={proc.pid}")

    except Exception as e:
        error_msg = "claude CLI not found" if isinstance(e, FileNotFoundError) else str(e)
        logger.error(f"[async] Failed to execute: {error_msg}")
        await execute(
            """INSERT INTO executions
               (id, schedule_id, pid, status, command, work_dir, issue_key, started_at, finished_at, error_message)
               VALUES (?, ?, NULL, 'error', ?, ?, ?, ?, ?, ?)""",
            (execution_id, schedule_id, command, work_dir, issue_key, now, now, error_msg),
        )

    return execution_id


# ─── 모드 2: Sync (시스템 작업용) ──────────────────────────────────────

async def run_claude_sync(
    args: list[str],
    timeout: int = 120,
    work_dir: str | None = None,
) -> dict:
    """
    claude CLI를 실행하고 stdout 결과를 받아서 반환.
    토큰 체크, SuperSkills 로그인 등 결과가 필요한 시스템 작업용.
    
    Returns:
        {
            "success": bool,
            "stdout": str,       # 원본 stdout
            "stderr": str,       # 원본 stderr
            "json": dict | None, # stdout이 JSON이면 파싱된 결과
            "returncode": int,
            "duration_seconds": int,
        }
    """
    command_str = "claude " + " ".join(args)
    logger.info(f"[sync] Executing: {command_str}")

    started = datetime.now()

    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", *args,
            cwd=work_dir,
            env=_clean_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            duration = int((datetime.now() - started).total_seconds())
            logger.error(f"[sync] Timeout after {timeout}s: {command_str}")
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Timeout after {timeout}s",
                "json": None,
                "returncode": -1,
                "duration_seconds": duration,
            }

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        duration = int((datetime.now() - started).total_seconds())

        # stdout에서 JSON 파싱 시도
        parsed_json = None
        if stdout:
            try:
                parsed_json = json.loads(stdout)
            except json.JSONDecodeError:
                # JSON이 아닌 텍스트 응답 → stdout에서 JSON 블록 추출 시도
                parsed_json = _extract_json_from_text(stdout)

        success = proc.returncode == 0
        logger.info(f"[sync] Completed (rc={proc.returncode}, {duration}s): {command_str}")

        return {
            "success": success,
            "stdout": stdout,
            "stderr": stderr,
            "json": parsed_json,
            "returncode": proc.returncode,
            "duration_seconds": duration,
        }

    except FileNotFoundError:
        logger.error("claude CLI not found. Is Claude Code installed?")
        return {
            "success": False,
            "stdout": "",
            "stderr": "claude CLI not found",
            "json": None,
            "returncode": -1,
            "duration_seconds": 0,
        }
    except Exception as e:
        logger.error(f"[sync] Failed: {e}")
        return {
            "success": False,
            "stdout": "",
            "stderr": str(e),
            "json": None,
            "returncode": -1,
            "duration_seconds": 0,
        }


def _extract_json_from_text(text: str) -> dict | None:
    """텍스트 응답에서 JSON 블록을 찾아 파싱"""
    # ```json ... ``` 블록 추출
    match = re.search(r'```json\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # { ... } 블록 추출
    match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None
