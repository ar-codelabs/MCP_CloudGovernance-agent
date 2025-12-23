#!/bin/bash

echo "🚀 CMDB MCP 서버 & Streamlit 챗봇 시작"

# cmdbmcp 가상환경 생성 및 활성화
if [ ! -d "cmdbmcp" ]; then
    echo "📦 cmdbmcp 가상환경 생성 중..."
    python3 -m venv cmdbmcp
fi

source cmdbmcp/bin/activate

# 패키지 설치
echo "📦 패키지 설치 중..."
pip3 install -r requirements.txt

# 환경 변수 확인
if [ ! -f ".env" ]; then
    echo "⚠️  .env 파일을 .env.example을 참고하여 생성해주세요"
    echo "cp .env.example .env"
    echo "그 후 실제 AWS 자격증명을 입력하세요"
    exit 1
fi

# Streamlit 앱 실행 (MCP 서버 자동 시작)
echo "🌟 Streamlit 챗봇 시작 (MCP 서버 자동 시작)..."
python3 -m streamlit run streamlit_app.py --server.port 8504 --server.address 0.0.0.0

echo "✅ 완료!"