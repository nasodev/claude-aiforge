# AIForge

AI 업무 자동화를 위한 프로젝트 및 스케줄 관리 시스템

## 개요

이 프로젝트는 Claude Code 스킬을 주기적으로 실행하고 실행 관리를 목적으로 합니다. 실제 스킬 동작은 workspace에 복사한 스킬을 따릅니다.

## Quick Start

소스 클론 후 Claude Code를 실행하고 아래 프롬프트를 입력합니다.

```
README.md 파일을 보고 설치 및 실행 하시오
```

## 설치 및 실행

```bash
# 소스 클론
git clone https://github.com/nasodev/claude-aiforge.git

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 서버 실행 (8010 포트)
python run.py
```

## Workspace 구성

`workspace/` 폴더 하위에 원하는 작업 폴더를 생성하고, 해당 폴더에 사용할 스킬이 들어있는 `.claude` 폴더를 복사해서 넣어줍니다.

```
workspace/
├── system/              # 시스템 폴더 (서버 실행 시 자동 생성)
├── fas-master/          # FAS 마스터 스킬용 작업 폴더
│   └── .claude/         # 스킬 설정
├── bmsvc-sonar/         # 소나큐브 이슈 처리용 작업 폴더
│   └── .claude/         # 스킬 설정
└── ...
```

## 로그 보기 (선택)

로그 뷰어를 사용하려면 [claude-code-log](https://github.com/daaain/claude-code-log)를 설치합니다.

```bash
git clone https://github.com/daaain/claude-code-log.git
cd claude-code-log
uv sync
```

설치 후 로그를 확인할 workspace 폴더명을 지정하여 사용합니다.
