import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.database import fetch_all, fetch_one, execute, get_setting, update_setting
from app.services.executor import run_claude_async, run_claude_sync
from app.services.log_checker import check_running_executions
from app.utils import safe_int

logger = logging.getLogger("aiforge.scheduler")

SYSTEM_WORK_DIR = str(Path(__file__).resolve().parent.parent.parent / "workspace" / "system")

scheduler = AsyncIOScheduler()
_background_tasks: set[asyncio.Task] = set()


async def init_scheduler():
    """스케줄러 초기화: DB에서 스케줄 로드 + 시스템 작업 등록"""
    await _register_system_jobs()
    await _register_project_schedules()
    scheduler.start()
    logger.info("Scheduler started")


async def _register_system_jobs():
    """설정에 따라 시스템 작업 등록"""

    # 로그 모니터 (실행 중인 execution 상태 체크)
    log_monitor = await get_setting("log_monitor_config")
    if log_monitor and log_monitor.get("enabled"):
        interval = log_monitor.get("interval_minutes", 10)
        scheduler.add_job(
            _job_check_logs,
            "interval",
            minutes=interval,
            id="system_log_monitor",
            replace_existing=True,
        )
        logger.info(f"Log monitor registered: every {interval} min")

    # 토큰 사용량 체크
    token_config = await get_setting("token_check_config")
    if token_config and token_config.get("enabled"):
        interval = token_config.get("interval_minutes", 60)
        scheduler.add_job(
            _job_check_token,
            "interval",
            minutes=interval,
            id="system_token_check",
            replace_existing=True,
        )
        logger.info(f"Token check registered: every {interval} min")



async def _register_project_schedules():
    """DB에서 활성화된 스케줄을 로드하여 APScheduler에 등록"""
    schedules = await fetch_all(
        """SELECT s.*, p.type, p.jira_project, p.jira_label, p.jira_status
           FROM schedules s
           JOIN projects p ON s.project_id = p.id
           WHERE s.enabled = 1 AND p.enabled = 1"""
    )

    for sched in schedules:
        await register_schedule(sched)

    logger.info(f"Registered {len(schedules)} project schedules")


async def register_schedule(sched: dict):
    """개별 스케줄을 APScheduler에 등록"""
    job_id = f"schedule_{sched['id']}"

    try:
        trigger = CronTrigger.from_crontab(sched["cron_expr"])
    except ValueError as e:
        logger.error(f"Invalid cron expression for {sched['id']}: {e}")
        return

    scheduler.add_job(
        _job_run_schedule,
        trigger,
        id=job_id,
        replace_existing=True,
        kwargs={"schedule_id": sched["id"]},
    )

    # next_run_at 업데이트
    await _update_next_run_at(sched["id"])

    logger.info(f"Registered schedule {sched['id']} ({sched.get('name', '')}) cron={sched['cron_expr']}")


async def unregister_schedule(schedule_id: str):
    """스케줄을 APScheduler에서 제거"""
    job_id = f"schedule_{schedule_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info(f"Unregistered schedule {schedule_id}")


async def reload_all():
    """모든 스케줄 재로드 (설정 변경 시)"""
    for job in scheduler.get_jobs():
        if job.id.startswith("schedule_") or job.id.startswith("system_"):
            scheduler.remove_job(job.id)

    await _register_system_jobs()
    await _register_project_schedules()
    logger.info("All schedules reloaded")


# ─── Project Job ──────────────────────────────────────────────────────

async def _job_run_schedule(schedule_id: str):
    """프로젝트 스케줄 실행 (fire-and-forget)"""

    if await _is_token_limit_exceeded():
        logger.warning(f"Token limit exceeded, skipping schedule {schedule_id}")
        return

    sched = await fetch_one(
        """SELECT s.*, p.type, p.jira_project, p.jira_label, p.jira_status
           FROM schedules s
           JOIN projects p ON s.project_id = p.id
           WHERE s.id = ?""",
        (schedule_id,),
    )

    if not sched:
        logger.error(f"Schedule {schedule_id} not found")
        return

    if sched["type"] == "jira":
        await _execute_jira_schedule(sched)
    else:
        await _execute_direct_schedule(sched)

    # 실행 후 next_run_at 갱신
    await _update_next_run_at(schedule_id)


async def _execute_jira_schedule(sched: dict):
    """JIRA 타입: claude CLI로 JIRA 폴링 → 이슈별 claude 실행 (fire-and-forget)"""

    # 검색 조건 조립
    parts = []
    if sched.get("jira_project"):
        parts.append(f"프로젝트:{sched['jira_project']}")
    if sched.get("jira_label"):
        parts.append(f"label:{sched['jira_label']}")
    if sched.get("jira_status"):
        parts.append(f"status:{sched['jira_status']}")
    conditions = " ".join(parts)

    poll_prompt = (
        f"다음 조건에 해당하는 JIRA 검색 해줘 {conditions} "
        "조회해서 json 으로 알려줘 출력에 다른값은 넣지 않고 json 만 넣어줘"
    )

    logger.info(f"[jira_poll] CLI로 JIRA 조회 중: {conditions}")

    result = await run_claude_sync(
        args=["--dangerously-skip-permissions", "--chrome", "-p", poll_prompt],
        timeout=180,
        work_dir=sched["work_dir"],
    )

    if not result["success"]:
        logger.error(f"[jira_poll] CLI 실패: {result['stderr']}")
        return

    issues = result.get("json")
    if not issues:
        logger.info(f"[jira_poll] No issues found for schedule {sched['id']}")
        if result["stdout"]:
            logger.info(f"[jira_poll] raw stdout: {result['stdout'][:300]}")
        return

    # JSON이 리스트가 아니면 issues 키에서 추출 시도
    if isinstance(issues, dict):
        issues = issues.get("issues", [])

    if not issues:
        logger.info(f"[jira_poll] No issues in response for schedule {sched['id']}")
        return

    logger.info(f"[jira_poll] Found {len(issues)} issues")

    # 이미 실행 완료되었거나 실행 중인 이슈 키 조회
    executed = await fetch_all(
        "SELECT issue_key FROM executions WHERE schedule_id = ? AND status IN ('running', 'success')",
        (sched["id"],),
    )
    executed_keys = {r["issue_key"] for r in executed if r["issue_key"]}

    for issue in issues:
        issue_key = issue.get("key", "")
        if not issue_key:
            continue
        if issue_key in executed_keys:
            logger.info(f"[jira_poll] Skipping {issue_key} — already executed or running")
            continue
        prompt = sched["prompt_template"].replace("{issue_key}", issue_key)
        await run_claude_async(
            schedule_id=sched["id"],
            work_dir=sched["work_dir"],
            prompt=prompt,
            issue_key=issue_key,
        )


async def _execute_direct_schedule(sched: dict):
    """Schedule 타입: 프롬프트 직접 실행 (fire-and-forget)"""
    await run_claude_async(
        schedule_id=sched["id"],
        work_dir=sched["work_dir"],
        prompt=sched["prompt_template"],
    )


# ─── System Jobs (sync - 결과 대기) ──────────────────────────────────

async def _job_check_logs():
    """실행 중인 execution 상태 체크"""
    logger.info("Running log check...")
    await check_running_executions()

    status = await get_setting("log_monitor_status") or {}
    status["last_checked"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    await update_setting("log_monitor_status", status)


CLAUDE_USAGE_PROMPT = (
    "브라우저에서 이미 claude.ai/settings/usage 탭이 열려있는지 확인해줘. "
    "열려있으면 그 탭으로 이동해서 새로고침하고, 없으면 새 탭으로 접속해줘. "
    "페이지가 완전히 로드될때까지 충분히 기다린 후 스크린샷을 찍어줘. "
    "사용량 숫자가 보이는지 확인하고, 플랜 사용량 한도(세션)와 주간 한도 퍼센트를 "
    "다음 JSON 형식으로만 알려줘:\n"
    '{"current_session_percent": 숫자, "weekly_limit_percent": 숫자}'
)


async def _job_check_token():
    """스케줄러에서 호출 — 이벤트 루프 블로킹 방지를 위해 백그라운드 태스크로 실행"""
    task = asyncio.create_task(_do_check_token())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    logger.info("[token_check] 백그라운드 태스크 시작")


async def _do_check_token():
    """
    Claude 토큰 사용량 체크 (실제 로직).
    claude CLI를 sync로 실행하여 결과 JSON을 파싱.

    실행 명령:
      claude --dangerously-skip-permissions --chrome -p '<PROMPT>'

    기대 응답:
      {"current_session_percent": 4, "weekly_limit_percent": 5}
    """
    logger.info("[token_check] 시작 - claude CLI 호출 중...")
    started = datetime.now()

    result = await run_claude_sync(
        args=["--dangerously-skip-permissions", "--chrome", "-p", CLAUDE_USAGE_PROMPT],
        timeout=180,
        work_dir=SYSTEM_WORK_DIR,
    )

    elapsed = int((datetime.now() - started).total_seconds())
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    status = await get_setting("token_check_status") or {}
    status["last_checked"] = now

    logger.info(
        f"[token_check] CLI 완료 ({elapsed}s) - "
        f"returncode={result['returncode']}, "
        f"stdout={len(result['stdout'])}chars, "
        f"json={'있음' if result['json'] else '없음'}"
    )

    if result["success"] and result["json"]:
        data = result["json"]
        status["current_session_percent"] = safe_int(data.get("current_session_percent"), safe_int(status.get("current_session_percent")))
        status["weekly_limit_percent"] = safe_int(data.get("weekly_limit_percent"), safe_int(status.get("weekly_limit_percent")))
        status["raw_response"] = result["stdout"][:500]
        status["error"] = None
        logger.info(
            f"[token_check] 성공 - session={status['current_session_percent']}%, "
            f"weekly={status['weekly_limit_percent']}%"
        )
    else:
        status["error"] = result["stderr"] or "Failed to parse response"
        status["raw_response"] = result["stdout"][:500]
        logger.error(f"[token_check] 실패 - error={status['error']}")
        if result["stdout"]:
            logger.error(f"[token_check] raw stdout: {result['stdout'][:300]}")

    await update_setting("token_check_status", status)

    # 한도 초과 시 경고 로그
    config = await get_setting("token_check_config") or {}
    session = safe_int(status.get("current_session_percent"))
    weekly = safe_int(status.get("weekly_limit_percent"))
    if session >= safe_int(config.get("session_limit_percent"), 80):
        logger.warning(f"[token_check] 세션 사용량 {session}% - 한도 초과!")
    if weekly >= safe_int(config.get("weekly_limit_percent"), 70):
        logger.warning(f"[token_check] 주간 사용량 {weekly}% - 한도 초과!")


# ─── Helpers ──────────────────────────────────────────────────────────

async def _update_next_run_at(schedule_id: str):
    """APScheduler에서 다음 실행 시간을 가져와 DB에 갱신"""
    job = scheduler.get_job(f"schedule_{schedule_id}")
    if not job:
        return
    next_run_time = getattr(job, "next_run_time", None)
    if next_run_time:
        next_run = next_run_time.strftime("%Y-%m-%dT%H:%M:%S")
        await execute(
            "UPDATE schedules SET next_run_at = ? WHERE id = ?",
            (next_run, schedule_id),
        )


async def _is_token_limit_exceeded() -> bool:
    """토큰 한도 초과 여부 체크"""
    global_setting = await get_setting("global")
    if not global_setting or not global_setting.get("auto_pause_on_limit"):
        return False

    config = await get_setting("token_check_config")
    if not config or not config.get("enabled"):
        return False

    status = await get_setting("token_check_status") or {}
    session = safe_int(status.get("current_session_percent"))
    weekly = safe_int(status.get("weekly_limit_percent"))
    session_limit = safe_int(config.get("session_limit_percent"), 80)
    weekly_limit = safe_int(config.get("weekly_limit_percent"), 70)

    return session >= session_limit or weekly >= weekly_limit
