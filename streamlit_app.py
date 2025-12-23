import streamlit as st
import boto3
import json
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
from dotenv import load_dotenv
import subprocess
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 환경 변수 로드
load_dotenv()

# AWS Bedrock 설정
bedrock = boto3.client('bedrock-runtime', region_name='us-east-1')
s3_client = boto3.client('s3')

# 페이지 설정
st.set_page_config(
    page_title="🔍 CMDB 챗봇",
    page_icon="🔍",
    layout="wide"
)

# 사이드바 설정
st.sidebar.title("🔍 CMDB 설정")
S3_BUCKET = st.sidebar.text_input("S3 버킷", value="mwaa-cmdb-bucket")

def get_latest_date():
    """S3에서 가장 최근 날짜 폴더 찾기"""
    try:
        response = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix='aws-policies/',
            Delimiter='/'
        )
        dates = [p['Prefix'].split('/')[-2] for p in response.get('CommonPrefixes', [])]
        return max(dates) if dates else datetime.now().strftime('%Y%m%d')
    except Exception as e:
        st.error(f"날짜 조회 오류: {e}")
        return datetime.now().strftime('%Y%m%d')

def list_s3_structure():
    """S3 버킷 구조 확인"""
    try:
        response = s3_client.list_objects_v2(Bucket=S3_BUCKET, MaxKeys=20)
        return [obj['Key'] for obj in response.get('Contents', [])]
    except Exception as e:
        return [f"오류: {e}"]

import re

def anonymize_data(data):
    """민감 정보 익명화 (포괄적 버전)"""
    try:
        if isinstance(data, dict):
            # 딕셔너리 키도 익명화 처리
            anonymized_dict = {}
            for k, v in data.items():
                # 키가 AWS Account ID인지 확인
                if isinstance(k, str) and re.match(r'^\d{12}$', k):
                    anonymized_key = k[:3] + '*' * 9  # Account ID 익명화
                else:
                    anonymized_key = anonymize_data(k) if isinstance(k, str) else k
                
                anonymized_dict[anonymized_key] = anonymize_data(v)
            return anonymized_dict
        elif isinstance(data, list):
            return [anonymize_data(item) for item in data]
        elif isinstance(data, str):
            # 정책명/롤명/그룹명은 익명화하지 않음 (비즈니스 로직 파악에 필요)
            # AWS 리소스 이름 패턴 (정책, 롤, 그룹, 사용자명 등)
            if (len(data) < 100 and  # 너무 긴 문자열은 제외
                not re.match(r'^\d{12}$', data) and  # Account ID 아님
                not data.startswith('AKIA') and  # Access Key 아님
                not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', data) and  # IP 주소 아님
                not data.startswith('arn:aws:') and  # ARN 아님
                not '@' in data and  # 이메일 아님
                not re.match(r'^[A-Za-z0-9+/=_-]{40,}$', data)):  # 긴 토큰 아님 (40자 이상)
                # 일반적인 AWS 리소스 이름이라고 판단되면 그대로 반환
                return data
            # 1. 인증 정보 익명화
            # AWS Account ID (12자리)
            if re.match(r'^\d{12}$', data):
                return data[:3] + '*' * 9
            
            # Access Key ID
            if data.startswith('AKIA') and len(data) == 20:
                return data[:8] + '*' * 12
            
            # Secret Access Key (완전 마스킹)
            if len(data) == 40 and re.match(r'^[A-Za-z0-9+/]+$', data):
                return data[:4] + '*' * 36
            
            # API 키, 토큰 (긴 영숫자 문자열)
            if len(data) > 20 and re.match(r'^[A-Za-z0-9+/=_-]+$', data):
                return data[:4] + '*' * (len(data) - 4)
            
            # 2. 보안 설정 익명화
            # 내부 IP 주소 (10.x.x.x, 172.16-31.x.x, 192.168.x.x)
            if re.match(r'^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)', data):
                parts = data.split('.')
                return f"{parts[0]}.{parts[1]}.*.**"
            
            # 일반 IP 주소
            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', data):
                parts = data.split('.')
                return f"{parts[0]}.*.*.**"
            
            # 포트 범위 (1024-65535)
            if re.match(r'^\d{4,5}$', data) and 1024 <= int(data) <= 65535:
                return '***'
            
            # KMS Key ID (실제 키 값 마스킹, ID는 유지)
            if data.startswith('arn:aws:kms:') and 'key/' in data:
                return data  # KMS Key ID는 유지
            
            # 3. 내부 정보 익명화
            # 내부 도메인
            if re.match(r'.*\.(internal|local|corp|company)$', data):
                return '***.' + data.split('.')[-1]
            
            # 이메일 주소
            if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', data):
                return '***@***.***'
            
            # ARN 익명화 (계정 ID 부분만)
            if data.startswith('arn:aws:'):
                parts = data.split(':')
                if len(parts) >= 5 and re.match(r'^\d{12}$', parts[4]):
                    parts[4] = parts[4][:3] + '*' * 9
                    return ':'.join(parts)
            
            # AWS 리소스 ID
            if re.match(r'^(vpc|subnet|sg|i|vol|snap|ami|key|db|rtb|igw|nat|eni)-[a-zA-Z0-9]+$', data):
                prefix = data.split('-')[0]
                suffix = data.split('-')[1]
                if len(suffix) > 3:
                    return f"{prefix}-{suffix[:3]}***"
                else:
                    return f"{prefix}-***"
            
            # 정책명/롤명은 익명화하지 않음 (비즈니스 로직 파악에 필요)
            # PolicyName, RoleName, GroupName 등은 그대로 유지
            
            # 데이터베이스 연결 문자열
            if any(keyword in data.lower() for keyword in ['password=', 'pwd=', 'user=', 'uid=']):
                return '***'
            
            # 호스트명 (내부 서버)
            if re.match(r'^[a-zA-Z0-9-]+\.(internal|local|corp)$', data):
                return '***.' + data.split('.')[-1]
            
            return data
        else:
            return data
    except Exception as e:
        # 익명화 실패시 원본 데이터 반환
        return data

def load_cmdb_data(category, date=None, anonymize=True):
    """S3에서 CMDB 데이터 로드 (선택적 익명화)"""
    if not date:
        date = get_latest_date()
    
    key = f"aws-policies/{date}/{category}.json"
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        # 익명화 선택적 적용
        if anonymize:
            return anonymize_data(data)
        else:
            return data
    except Exception as e:
        return {"error": str(e)}

# MCP 서버 자동 시작
@st.cache_resource
def start_mcp_server():
    """MCP 서버 자동 시작"""
    import subprocess
    import time
    import psutil
    
    # 이미 실행 중인 MCP 서버 확인
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'mcp_server.py' in ' '.join(proc.info['cmdline'] or []):
                st.success(f"✅ MCP 서버가 이미 실행 중입니다 (PID: {proc.info['pid']})")
                return proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    # MCP 서버 시작
    try:
        process = subprocess.Popen(
            ['python', 'mcp_server.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(2)  # 서버 시작 대기
        
        if process.poll() is None:  # 프로세스가 살아있음
            st.success(f"✅ MCP 서버 시작됨 (PID: {process.pid})")
            return process.pid
        else:
            st.error("❌ MCP 서버 시작 실패")
            return None
    except Exception as e:
        st.error(f"❌ MCP 서버 시작 오류: {e}")
        return None

# MCP 클라이언트 설정
@st.cache_resource
def get_mcp_client():
    """MCP 서버 클라이언트 초기화"""
    # MCP 서버 자동 시작
    server_pid = start_mcp_server()
    if not server_pid:
        return None
    
    try:
        server_params = StdioServerParameters(
            command="python",
            args=["mcp_server.py"],
            env=None
        )
        return server_params
    except Exception as e:
        st.error(f"MCP 서버 연결 실패: {e}")
        return None

async def call_mcp_tool_async(tool_name, **kwargs):
    """실제 MCP 서버 도구 호출"""
    server_params = get_mcp_client()
    if not server_params:
        return {"error": "MCP 서버 연결 실패"}
    
    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # 도구 호출
                result = await session.call_tool(tool_name, kwargs)
                return result.content[0].text if result.content else {"error": "응답 없음"}
    except Exception as e:
        return {"error": str(e)}

def call_mcp_tool(tool_name, **kwargs):
    """동기 래퍼 함수"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(call_mcp_tool_async(tool_name, **kwargs))
        loop.close()
        
        # JSON 문자열인 경우 파싱
        if isinstance(result, str):
            try:
                return json.loads(result)
            except json.JSONDecodeError:
                return {"error": f"JSON 파싱 실패: {result}"}
        return result
    except Exception as e:
        return {"error": str(e)}

def select_mcp_tools(prompt):
    """Bedrock이 필요한 MCP 도구 선택"""
    tool_selection_prompt = f"""
질문: {prompt}

다음 CMDB 도구 중 필요한 것들을 선택하세요:

- get_identity_policies: IAM 사용자, 역할, 그룹, 정책, 권한 관련
  예: "IAM 역할", "CloudWatch 권한", "관리자 권한", "정책", "사용자"
  
- get_storage_policies: S3 버킷, EFS, FSx 스토리지 관련
  예: "S3 버킷", "스토리지", "파일 시스템"
  
- get_compute_policies: EC2 인스턴스, Lambda, ECS 컴퓨팅 관련
  예: "EC2", "Lambda", "컨테이너", "인스턴스"
  
- get_database_policies: RDS, DynamoDB 데이터베이스 관련
  예: "RDS", "데이터베이스", "DynamoDB"
  
- get_network_policies: VPC, 서브넷, 보안그룹, CloudFront, Route53 네트워크 관련
  예: "VPC", "네트워크", "보안그룹", "서브넷"
  
- get_security_policies: KMS, Secrets Manager, WAF 보안 관련
  예: "KMS", "암호화", "시크릿", "WAF"
  
- search_resources: 특정 리소스 이름이나 ID로 검색
  예: "특정 버킷 찾기", "리소스 검색"
  
- get_resource_summary: 전체 리소스 개수 및 요약
  예: "전체 현황", "리소스 수", "요약"

중요: 
- "권한", "역할", "정책", "사용자" 관련 질문은 반드시 get_identity_policies 선택
- CloudWatch, S3, EC2 등 서비스 권한 질문도 get_identity_policies 선택
- 여러 도구가 필요하면 모두 선택

필요한 도구들을 콤마로 구분해서 답하세요. 예: get_identity_policies,get_storage_policies
도구 이름만 답하세요.
"""
    
    try:
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 100,
            "messages": [
                {
                    "role": "user",
                    "content": tool_selection_prompt
                }
            ]
        })
        
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=body
        )
        
        result = json.loads(response['body'].read())
        tools_text = result['content'][0]['text'].strip()
        
        # 콤마로 분리하여 도구 목록 생성
        tools = [tool.strip() for tool in tools_text.split(',') if tool.strip()]
        return tools
    
    except Exception as e:
        # 오류 시 기본 도구 반환
        return ["get_resource_summary"]

def query_bedrock_with_mcp_tools(prompt):
    """MCP 도구를 활용한 Bedrock 질의"""
    try:
        # 1. 필요한 MCP 도구 선택
        selected_tools = select_mcp_tools(prompt)
        
        # 2. 선택된 도구들로 데이터 수집
        context_data = {}
        for tool in selected_tools:
            if "search_resources" in tool:
                # 검색 쿼리 추출
                search_query = prompt.split()
                query = " ".join([word for word in search_query if len(word) > 2])[:50]
                context_data[tool] = call_mcp_tool(tool, query=query)
            else:
                context_data[tool] = call_mcp_tool(tool)
        
        # 3. 질문에서 키워드 추출 (필터링용)
        keywords = []
        prompt_lower = prompt.lower()
        # 서비스명 키워드
        service_keywords = ['cloudwatch', 's3', 'ec2', 'rds', 'lambda', 'dynamodb', 
                           'vpc', 'iam', 'kms', 'sns', 'sqs', 'ecs', 'eks']
        for keyword in service_keywords:
            if keyword in prompt_lower:
                keywords.append(keyword)
        
        # 4. 데이터 필터링 (키워드가 있으면)
        if keywords:
            filtered_data = {}
            for tool_name, tool_data in context_data.items():
                if isinstance(tool_data, dict):
                    filtered_accounts = {}
                    for account_id, account_data in tool_data.items():
                        if isinstance(account_data, dict):
                            filtered_services = {}
                            for service_name, resources in account_data.items():
                                # 리소스 필터링
                                if isinstance(resources, list):
                                    filtered_resources = []
                                    for resource in resources:
                                        resource_str = json.dumps(resource, default=str).lower()
                                        # 키워드가 포함된 리소스만 선택
                                        if any(kw in resource_str for kw in keywords):
                                            filtered_resources.append(resource)
                                    if filtered_resources:
                                        filtered_services[service_name] = filtered_resources
                                else:
                                    filtered_services[service_name] = resources
                            if filtered_services:
                                filtered_accounts[account_id] = filtered_services
                        else:
                            filtered_accounts[account_id] = account_data
                    if filtered_accounts:
                        filtered_data[tool_name] = filtered_accounts
                else:
                    filtered_data[tool_name] = tool_data
            
            # 필터링된 데이터가 있으면 사용, 없으면 원본 사용
            if filtered_data:
                context_data = filtered_data
        
        # 5. 수집된 데이터로 최종 답변 생성
        # 데이터 크기 제한을 늘림 (15000 → 30000)
        context = json.dumps(context_data, indent=2, default=str, ensure_ascii=False)[:30000]
        
        full_prompt = f"""
당신은 AWS CMDB 전문가입니다. 다음 MCP 도구로 수집한 CMDB 데이터를 바탕으로 질문에 답해주세요.

사용된 MCP 도구: {', '.join(selected_tools)}
검색 키워드: {', '.join(keywords) if keywords else '없음'}

CMDB 데이터:
{context}


질문: {prompt}

중요 지침:
1. 제공된 데이터를 꼼꼼히 분석하세요
2. IAM 역할, 정책, 권한 정보가 있다면 반드시 활용하세요
3. CloudWatch, S3, EC2 등 서비스명이 포함된 역할/정책을 찾으세요
4. 데이터가 있는데 "없다"고 답하지 마세요
5. 구체적인 역할명, 정책명, ARN을 포함해서 답변하세요

답변은 한국어로, 구체적이고 실용적으로 제공해주세요.
"""
        
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "messages": [
                {
                    "role": "user",
                    "content": full_prompt
                }
            ]
        })
        
        response = bedrock.invoke_model(
            modelId='anthropic.claude-3-sonnet-20240229-v1:0',
            body=body
        )
        
        result = json.loads(response['body'].read())
        ai_response = result['content'][0]['text']
        
        # AI 답변에서 민감 정보 익명화
        ai_response = anonymize_ai_response(ai_response)
        
        return ai_response
    
    except Exception as e:
        return f"MCP 도구 활용 오류: {str(e)}"

def anonymize_ai_response(text):
    """AI 답변에서 민감 정보 익명화"""
    import re
    
    # 1. AWS Account ID (12자리 숫자)
    text = re.sub(r'\b(\d{3})\d{9}\b', r'\1*********', text)
    
    # 2. ARN의 계정 ID 부분만 익명화
    def anonymize_arn(match):
        arn = match.group(0)
        parts = arn.split(':')
        if len(parts) >= 5 and re.match(r'^\d{12}$', parts[4]):
            parts[4] = parts[4][:3] + '*' * 9
        return ':'.join(parts)
    
    text = re.sub(r'arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:[^\s]+', anonymize_arn, text)
    
    # 3. Access Key ID
    text = re.sub(r'\b(AKIA[A-Z0-9]{4})[A-Z0-9]{12}\b', r'\1************', text)
    
    # 4. IP 주소 (마지막 두 옥텟만 마스킹)
    text = re.sub(r'\b(\d{1,3}\.\d{1,3}\.)\d{1,3}\.\d{1,3}\b', r'\1*.**', text)
    
    # 5. 이메일 주소
    text = re.sub(r'\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b', '***@***.***', text)
    
    return text

def create_resource_summary():
    """리소스 요약 대시보드"""
    st.subheader("📊 리소스 요약")
    
    categories = {
        'identity_policies': 'IAM & 인증',
        'storage_policies': '스토리지',
        'compute_policies': '컴퓨팅',
        'database_policies': '데이터베이스',
        'network_policies': '네트워킹',
        'security_policies': '보안'
    }
    
    col1, col2, col3 = st.columns(3)
    
    summary_data = []
    for cat_key, cat_name in categories.items():
        data = load_cmdb_data(cat_key)
        if 'error' not in data:
            resource_count = 0
            for account_data in data.values():
                if isinstance(account_data, dict):
                    for service_data in account_data.values():
                        if isinstance(service_data, list):
                            resource_count += len(service_data)
            
            summary_data.append({
                'Category': cat_name,
                'Resources': resource_count,
                'Key': cat_key
            })
    
    if summary_data:
        df = pd.DataFrame(summary_data)
        
        with col1:
            fig = px.bar(df, x='Category', y='Resources', 
                        title='카테고리별 리소스 수')
            fig.update_layout(xaxis_tickangle=45)
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            fig = px.pie(df, values='Resources', names='Category',
                        title='리소스 분포')
            st.plotly_chart(fig, use_container_width=True)
        
        with col3:
            st.metric("총 리소스", df['Resources'].sum())
            st.metric("카테고리 수", len(df))
            st.metric("최신 데이터", get_latest_date())

def main():
    st.title("🔍 CMDB 챗봇")
    st.markdown("AWS/GCP CMDB 정책 데이터를 조회하고 분석하는 AI 챗봇입니다.")
    
    # 탭 생성
    tab1, tab2, tab3 = st.tabs(["💬 챗봇", "📊 대시보드", "🔍 데이터 탐색"])
    
    with tab1:
        st.subheader("💬 CMDB 질문하기")
        
        # 채팅 히스토리 초기화
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
        # 채팅 히스토리 표시
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        
        # 사용자 입력
        if prompt := st.chat_input("CMDB에 대해 질문해보세요 (예: IAM 정책 현황은?"):
            # 사용자 메시지 추가
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # AI 응답 생성
            with st.chat_message("assistant"):
                with st.spinner("분석 중..."):
                    # MCP 도구를 활용한 응답 생성
                    response = query_bedrock_with_mcp_tools(prompt)
                    st.markdown(response)
            
            # AI 응답 저장
            st.session_state.messages.append({"role": "assistant", "content": response})
    
    with tab2:
        create_resource_summary()
    
    with tab3:
        st.subheader("🔍 데이터 탐색")
        
        # S3 구조 확인
        if st.button("S3 버킷 구조 확인"):
            structure = list_s3_structure()
            st.write("📁 S3 버킷 파일 목록:")
            for item in structure[:10]:  # 처음 10개만 표시
                st.text(item)
        
        # 카테고리 선택
        category = st.selectbox(
            "카테고리 선택",
            ["identity_policies", "storage_policies", "compute_policies", 
             "database_policies", "network_policies", "security_policies"]
        )
        
        # 날짜 선택
        date = st.date_input("날짜 선택", value=datetime.now())
        date_str = date.strftime('%Y%m%d')
        
        # 예상 파일 경로 표시
        expected_key = f"aws-policies/{date_str}/{category}.json"
        st.info(f"📄 예상 파일 경로: {expected_key}")
        
        if st.button("데이터 로드"):
            # 데이터 탐색에서는 익명화 적용 (테이블 뷰 제외)
            data = load_cmdb_data(category, date_str, anonymize=True)
            # 테이블 뷰용 원본 데이터
            original_data = load_cmdb_data(category, date_str, anonymize=False)
            
            if 'error' in data:
                st.error(f"데이터 로드 실패: {data['error']}")
                st.warning("💡 해결 방법:")
                st.write("1. S3 버킷 구조를 확인해주세요")
                st.write("2. 날짜를 다른 날짜로 변경해보세요")
                st.write("3. AWS 자격증명을 확인해주세요")
            else:
                st.success(f"데이터 로드 성공: {category}")
                
                # 데이터 구조 디버깅
                st.write(f"📊 **데이터 타입**: {type(data)}")
                st.write(f"📊 **데이터 크기**: {len(data) if hasattr(data, '__len__') else 'N/A'}")
                
                if isinstance(data, dict):
                    st.write(f"🔑 **최상위 키**: {list(data.keys())[:10]}")
                    st.write(f"🔑 **전체 키 수**: {len(data.keys())}")
                    
                    # 빈 데이터 체크
                    if not data:
                        st.warning("⚠️ 데이터가 비어있습니다.")
                    else:
                        # 첫 번째 키의 데이터 구조 확인
                        first_key = list(data.keys())[0]
                        first_value = data[first_key]
                        st.write(f"🔍 **첫 번째 키 '{first_key}' 데이터 타입**: {type(first_value)}")
                        
                        if isinstance(first_value, dict):
                            st.write(f"🔍 **첫 번째 키의 서브키**: {list(first_value.keys())[:5]}")
                elif isinstance(data, list):
                    st.write(f"📊 **리스트 아이템 수**: {len(data)}")
                    if data:
                        st.write(f"🔍 **첫 번째 아이템 타입**: {type(data[0])}")
                
                # JSON 데이터 표시
                with st.expander("원본 JSON 데이터"):
                    st.json(data)
                
                # 구조화된 데이터 표시
                if isinstance(data, dict) and data:
                    data_found = False
                    for account_id, account_data in data.items():
                        if account_id == "error":  # 오류 키 건너뛰기
                            continue
                            
                        st.subheader(f"🏦 계정: {account_id}")
                        
                        if isinstance(account_data, dict) and account_data:
                            for service, resources in account_data.items():
                                st.write(f"⚙️ **{service}** (타입: {type(resources)})")
                                
                                if isinstance(resources, list):
                                    if resources:  # 비어있지 않은 리스트
                                        data_found = True
                                        st.write(f"📊 **{len(resources)}개 리소스**")
                                        
                                        # 테이블로 표시 (원본 데이터 사용하되 ARN 계정ID만 익명화)
                                        if isinstance(resources[0], dict):
                                            try:
                                                # 테이블 뷰에서는 완전히 원본 데이터 사용
                                                original_account_id = None
                                                # 익명화된 account_id에 대응하는 원본 찾기
                                                for orig_id in original_data.keys():
                                                    if orig_id.startswith(account_id[:3]):
                                                        original_account_id = orig_id
                                                        break
                                                
                                                if (original_account_id and 
                                                    original_account_id in original_data and
                                                    isinstance(original_data[original_account_id], dict) and
                                                    service in original_data[original_account_id] and
                                                    isinstance(original_data[original_account_id][service], list)):
                                                    # 원본 데이터에서 ARN의 계정 ID만 익명화
                                                    table_data = []
                                                    for item in original_data[original_account_id][service]:
                                                        if isinstance(item, dict):
                                                            anonymized_item = {}
                                                            for key, value in item.items():
                                                                if isinstance(value, str) and value.startswith('arn:aws:'):
                                                                    # ARN에서 계정 ID만 익명화
                                                                    parts = value.split(':')
                                                                    if len(parts) >= 5 and re.match(r'^\d{12}$', parts[4]):
                                                                        parts[4] = parts[4][:3] + '*' * 9
                                                                        anonymized_item[key] = ':'.join(parts)
                                                                    else:
                                                                        anonymized_item[key] = value
                                                                else:
                                                                    anonymized_item[key] = value
                                                            table_data.append(anonymized_item)
                                                        else:
                                                            table_data.append(item)
                                                    df = pd.DataFrame(table_data)
                                                else:
                                                    df = pd.DataFrame(resources)
                                                
                                                st.write("📋 **테이블 뷰**:")
                                                st.dataframe(df, use_container_width=True)
                                            except Exception as e:
                                                st.warning(f"테이블 변환 실패: {e}")
                                        else:
                                            # 리스트 데이터를 테이블로 표시
                                            try:
                                                df = pd.DataFrame([{'리소스': str(item)} for item in resources])
                                                st.dataframe(df, use_container_width=True)
                                            except Exception as e:
                                                st.warning(f"테이블 변환 실패: {e}")
                                    else:
                                        st.write("💭 빈 리스트")
                                elif isinstance(resources, dict):
                                    if resources:  # 비어있지 않은 딕셔너리
                                        data_found = True
                                        st.write("📋 **딕셔너리 데이터**:")
                                        st.json(resources)
                                    else:
                                        st.write("💭 빈 딕셔너리")
                                else:
                                    if resources:
                                        data_found = True
                                        st.write(f"📊 **데이터 타입**: {type(resources)}")
                                        st.text(str(resources)[:500])
                                    else:
                                        st.write("💭 빈 데이터")
                        else:
                            st.write(f"📊 **계정 데이터 타입**: {type(account_data)}")
                            if account_data:
                                data_found = True
                                st.text(str(account_data)[:500])
                            else:
                                st.write("💭 빈 계정 데이터")
                    
                    if not data_found:
                        st.warning("💭 모든 데이터가 비어있습니다.")
                else:
                    st.warning("💭 표시할 데이터가 없거나 비어있습니다.")

if __name__ == "__main__":
    main()