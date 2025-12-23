#!/bin/bash

# cmdbmcp 가상환경 생성 및 설정

echo "🔧 cmdbmcp 가상환경 생성 중..."

# 가상환경 생성
python3 -m venv cmdbmcp

# 가상환경 활성화
source cmdbmcp/bin/activate

echo "✅ 가상환경 활성화됨"

# 패키지 설치
echo "📦 패키지 설치 중..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎉 설정 완료!"
echo "가상환경 사용법:"
echo "  활성화: source cmdbmcp/bin/activate"
echo "  비활성화: deactivate"