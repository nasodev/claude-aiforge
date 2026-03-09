# AIForge - 프로젝트 분석서

## 1. 개요

**AIForge**는 Claude Code CLI를 자동화하여 스케줄 기반으로 AI 작업을 실행하고 관리하는 웹 대시보드 애플리케이션이다. JIRA 이슈 폴링이나 Cron 기반 반복 실행을 통해 Claude Code를 무인 운영할 수 있도록 설계되었다.

- **버전**: 0.1.0
- **런타임**: Python 3.12+ / FastAPI + Uvicorn
- **데이터베이스**: SQLite (aiosqlite, WAL 모드)
- **스케줄러**: APScheduler (AsyncIO)
- **UI**: Jinja2 SSR + 커스텀 CSS (다크 테마)

---

## 2. 디렉토리 구조

```
aiforge/latest/
├── run.py                  # 엔트리포인트 (uvicorn 실행)
├── requirements.txt        # Python 의존성
├── schema.sql              # DB 스키마 정의
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI 앱 설정, lifespan, 라우터 등록
│   ├── database.py         # DB 연결, 쿼리 헬퍼, 설정 관리
│   ├── models.py           # Pydantic 모델 (요청 검증)
│   ├── routes/
│   │   ├── dashboard.py    # GET / - 대시보드
│   │   ├── projects.py     # /projects CRUD
│   │   ├── schedules.py    # /schedules CRUD + 수동 실행
│   │   ├── executions.py   # /executions 실행 이력 조회/삭제
│   │   ├── settings.py     # /settings 설정 관리
│   │   └── logs.py         # /logs 로그 생성/조회
│   ├── services/
│   │   ├── scheduler.py    # APScheduler 초기화, 작업 등록/실행
│   │   ├── executor.py     # Claude CLI 실행 (async/sync 두 가지 모드)
│   │   ├── jira_client.py  # JIRA REST API 클라이언트 (미사용, 예비)
│   │   └── log_checker.py  # 실행 중인 프로세스 상태 점검 (PID 체크)
│   ├── static/
│   │   └── style.css       # 다크 테마 UI 스타일
│   └── templates/
│       ├── base.html       # 레이아웃 (헤더, 네비게이션)
│       ├── dashboard.html  # 대시보드 화면
│       ├── projects.html   # 프로젝트 목록
│       ├── project_form.html # 프로젝트 생성/수정 폼
│       ├── schedules.html  # 스케줄 목록
│       ├── schedule_form.html # 스케줄 생성/수정 폼
│       ├── executions.html # 실행 이력
│       ├── settings.html   # 설정 화면
│       └── logs.html       # 로그 조회 화면
└── workspace/              # 작업 디렉토리 (분석 제외)
```

---

## 3. 핵심 개념 및 데이터 모델

### 3.1 Projects (프로젝트)

Claude Code 자동화 작업의 최상위 단위.

| 필드 | 설명 |
|------|------|
| `id` | UUID (PK) |
| `name` | 프로젝트명 (UNIQUE) |
| `type` | `jira` 또는 `schedule` |
| `description` | 설명 |
| `enabled` | 활성/비활성 |
| `jira_project` | JIRA 프로젝트 키 (type=jira인 경우) |
| `jira_label` | JIRA 라벨 필터 |
| `jira_status` | JIRA 상태 필터 |

### 3.2 Schedules (스케줄)

프로젝트에 종속된 실행 스케줄 단위. Cron 표현식으로 실행 주기를 정의한다.

| 필드 | 설명 |
|------|------|
| `id` | UUID (PK) |
| `project_id` | FK → projects |
| `name` | 스케줄명 |
| `cron_expr` | Cron 표현식 (5자리) |
| `work_dir` | Claude CLI가 실행될 작업 디렉토리 |
| `prompt_template` | Claude에게 전달할 프롬프트 (JIRA 타입은 `{issue_key}` 치환) |
| `enabled` | 활성/비활성 |
| `status` | `idle` / `running` / `paused` / `error` |
| `run_count` | 누적 실행 횟수 |

### 3.3 Executions (실행 이력)

개별 Claude CLI 실행 기록.

| 필드 | 설명 |
|------|------|
| `id` | UUID (PK) |
| `schedule_id` | FK → schedules |
| `pid` | OS 프로세스 ID |
| `status` | `running` / `success` / `error` / `timeout` / `killed` |
| `command` | 실행된 CLI 명령어 |
| `work_dir` | 실행 디렉토리 |
| `issue_key` | JIRA 이슈 키 (해당 시) |
| `duration_seconds` | 실행 소요 시간 |
| `result_summary` | 결과 요약 |
| `error_message` | 에러 메시지 |

### 3.4 Settings (설정)

Key-Value 형태의 JSON 설정 저장소.

| 설정 키 | 용도 |
|---------|------|
| `token_check_config` | 토큰 사용량 체크 설정 (주기, 한도 %) |
| `token_check_status` | 토큰 사용량 현재 상태 |
| `log_monitor_config` | 로그 모니터 설정 (주기) |
| `log_monitor_status` | 로그 모니터 현재 상태 |
| `global` | 전역 설정 (auto_pause, max_concurrent 등) |

---

## 4. 아키텍처 및 동작 흐름

### 4.1 앱 시작 (Lifespan)

```
run.py → uvicorn → app.main:app
  ├── init_db()           # SQLite 스키마 생성 + 기본 설정 삽입
  └── init_scheduler()    # APScheduler 시작
       ├── _register_system_jobs()     # 토큰 체크, 로그 모니터 등록
       └── _register_project_schedules()  # DB에서 활성 스케줄 로드 → Cron 등록
```

### 4.2 실행 모드

**Mode 1 - Fire-and-Forget (비동기, 프로젝트 작업)**
```
스케줄 트리거 → _job_run_schedule()
  ├── 토큰 한도 체크 → 초과 시 skip
  ├── JIRA 타입 → _execute_jira_schedule()
  │     ├── Claude CLI로 JIRA 검색 (sync)
  │     └── 이슈별로 Claude CLI 실행 (async, fire-and-forget)
  └── Schedule 타입 → _execute_direct_schedule()
        └── Claude CLI 실행 (async, fire-and-forget)
```
- `run_claude_async()`: 프로세스를 띄우고 PID를 DB에 기록한 뒤 즉시 반환
- 프로세스 완료 감지는 `log_checker`의 PID 체크로 수행

**Mode 2 - Synchronous (동기, 시스템 작업)**
```
토큰 체크 → _job_check_token() → run_claude_sync()
  ├── Claude CLI 실행 (--chrome 플래그로 브라우저 사용)
  ├── claude.ai/settings/usage 페이지에서 사용량 스크래핑
  └── JSON 파싱 후 settings에 저장
```
- `run_claude_sync()`: 프로세스 완료까지 대기, stdout에서 JSON 추출

### 4.3 JIRA 연동 방식

JIRA API 직접 호출이 아닌, **Claude CLI + Chrome 브라우저**를 통해 JIRA를 폴링하는 방식이다.
- `jira_client.py`는 REST API 직접 호출 클라이언트이나 현재 실제 사용되지 않음
- 대신 `scheduler.py`의 `_execute_jira_schedule()`에서 Claude CLI에 프롬프트를 전달하여 JIRA 검색을 수행

### 4.4 토큰 사용량 관리

- 주기적으로 Claude CLI가 `claude.ai/settings/usage` 페이지를 브라우저로 열어 사용량 확인
- 세션 한도(기본 80%), 주간 한도(기본 70%) 초과 시 신규 스케줄 실행을 자동 중단
- `auto_pause_on_limit` 설정으로 제어

### 4.5 로그 모니터링

- `log_checker.py`: `psutil`로 PID 생존 여부 확인
- PID 사망 시 → 로그 파일 파싱으로 성공/실패 판단 → executions 상태 업데이트
- 스케줄의 running 상태를 idle로 복구

---

## 5. API 엔드포인트

### 대시보드
| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 대시보드 (통계, 최근 실행 등) |

### 프로젝트
| Method | Path | 설명 |
|--------|------|------|
| GET | `/projects` | 프로젝트 목록 |
| GET | `/projects/new` | 생성 폼 |
| GET | `/projects/{id}/edit` | 수정 폼 |
| POST | `/projects/create` | 프로젝트 생성 |
| POST | `/projects/{id}/update` | 프로젝트 수정 |
| POST | `/projects/{id}/toggle` | 활성/비활성 토글 |
| POST | `/projects/{id}/delete` | 프로젝트 삭제 |

### 스케줄
| Method | Path | 설명 |
|--------|------|------|
| GET | `/schedules` | 스케줄 목록 |
| GET | `/schedules/new` | 생성 폼 |
| GET | `/schedules/{id}/edit` | 수정 폼 |
| POST | `/schedules/create` | 스케줄 생성 |
| POST | `/schedules/{id}/update` | 스케줄 수정 |
| POST | `/schedules/{id}/toggle` | 활성/비활성 토글 |
| POST | `/schedules/{id}/run` | 수동 즉시 실행 |
| POST | `/schedules/{id}/delete` | 스케줄 삭제 |

### 실행 이력
| Method | Path | 설명 |
|--------|------|------|
| GET | `/executions` | 실행 이력 (필터: status, project) |
| POST | `/executions/clear` | 이력 초기화 (running 제외) |

### 설정
| Method | Path | 설명 |
|--------|------|------|
| GET | `/settings` | 설정 화면 |
| POST | `/settings/token_check` | 토큰 체크 설정 저장 |
| POST | `/settings/log_monitor` | 로그 모니터 설정 저장 |
| POST | `/settings/trigger/token_check` | 토큰 체크 수동 트리거 |
| POST | `/settings/trigger/log_monitor` | 로그 모니터 수동 트리거 |
| POST | `/settings/global` | 전역 설정 저장 |

### 로그
| Method | Path | 설명 |
|--------|------|------|
| GET | `/logs` | 로그 화면 |
| POST | `/logs/generate` | claude-code-log 실행하여 HTML 리포트 생성 |
| GET | `/logs/view` | 생성된 로그 HTML 조회 |
| GET | `/logs/view/{path}` | 특정 로그 파일 조회 |

---

## 6. 의존성

| 패키지 | 버전 | 용도 |
|--------|------|------|
| fastapi | 0.115.0 | 웹 프레임워크 |
| uvicorn | 0.30.6 | ASGI 서버 |
| jinja2 | 3.1.4 | 서버사이드 템플릿 |
| aiosqlite | 0.20.0 | 비동기 SQLite |
| apscheduler | 3.10.4 | Cron 스케줄러 |
| httpx | 0.27.2 | HTTP 클라이언트 (JIRA API용) |
| pydantic | 2.9.0 | 데이터 검증 |
| python-multipart | 0.0.9 | Form 파싱 |
| psutil | 6.0.0 | 프로세스 모니터링 |

외부 의존:
- **Claude Code CLI** (`claude`): 시스템 PATH에 설치 필요
- **uv** (선택): 로그 생성 시 `claude-code-log` 실행에 사용

---

## 7. 외부 연동

| 대상 | 방식 | 설명 |
|------|------|------|
| Claude Code CLI | subprocess | `claude --dangerously-skip-permissions --chrome -p <prompt>` |
| Claude.ai | Claude CLI + Chrome | 토큰 사용량 페이지 스크래핑 |
| JIRA | Claude CLI + Chrome | JIRA 이슈 검색 (CLI를 통한 간접 접근) |
| claude-code-log | subprocess (uv run) | 로그 리포트 HTML 생성 |

---

## 8. UI 특징

- **다크 테마**: `#0a0e14` 배경, `JetBrains Mono` 폰트 기반 개발자 친화적 UI
- **SSR 방식**: Jinja2 템플릿으로 서버사이드 렌더링, SPA 아님
- **한국어 인터페이스**: 네비게이션, 레이블 등 한국어 사용
- **반응형**: 768px 이하 모바일 대응
- **네비게이션**: 대시보드, 프로젝트, 스케줄, 실행이력, 로그보기, 설정
- **실시간 시계**: 헤더에 현재 시각 표시

---

## 9. 주요 설계 특성

1. **Claude CLI 중심 아키텍처**: JIRA API나 외부 서비스에 직접 연동하지 않고, Claude Code CLI를 중개자로 활용하여 브라우저 기반 작업을 수행
2. **Fire-and-Forget 패턴**: 장시간 실행되는 프로젝트 작업은 프로세스를 띄운 뒤 PID만 기록하고 주기적으로 생존 체크
3. **토큰 예산 관리**: 사용량 한도 초과 시 자동으로 신규 작업 실행을 차단
4. **환경변수 격리**: `CLAUDECODE` 환경변수를 제거하여 Claude CLI 중첩 실행 문제를 우회
5. **설정의 이원 구조**: 각 기능의 설정(`config`)과 런타임 상태(`status`)를 분리하여 DB에 저장
