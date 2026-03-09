#!/bin/bash
# AIForge 서버 종료 스크립트
PID=$(lsof -ti :8010)
if [ -n "$PID" ]; then
    kill $PID
    echo "AIForge 서버 종료됨 (PID: $PID)"
else
    echo "8010 포트에서 실행 중인 서버가 없습니다"
fi
