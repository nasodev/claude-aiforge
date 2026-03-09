#!/bin/bash

# AIForge 초기화 스크립트

# 8010 포트 프로세스 종료
PID=$(lsof -ti :8010)
if [ -n "$PID" ]; then
    kill $PID
    echo "8010 포트 프로세스 종료 (PID: $PID)"
else
    echo "8010 포트에 실행 중인 프로세스 없음"
fi

# venv 삭제
rm -rf venv
echo "venv 삭제 완료"

# DB 및 로그 삭제
rm -rf aiforge.db aiforge.db-shm aiforge.db-wal aiforge.log
echo "DB 및 로그 삭제 완료"

# __pycache__ 삭제
find . -type d -name __pycache__ -exec rm -rf {} +
echo "__pycache__ 삭제 완료"

echo "초기화 완료"
