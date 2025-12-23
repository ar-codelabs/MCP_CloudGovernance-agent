#!/usr/bin/env python3
"""
CMDB MCP Server
S3에 저장된 AWS/GCP CMDB 정책 데이터를 조회하는 MCP 서버
"""
import json
import boto3
from datetime import datetime
from mcp.server import Server
from mcp.types import Tool, TextContent
import mcp.server.stdio

# S3 설정
S3_BUCKET = "mwaa-cmdb-bucket"
s3_client = boto3.client('s3')

# MCP 서버 초기화
app = Server("cmdb-server")

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
    except:
        return datetime.now().strftime('%Y%m%d')

def load_cmdb_data(category, date=None):
    """S3에서 CMDB 데이터 로드"""
    if not date:
        date = get_latest_date()
    
    key = f"aws-policies/{date}/{category}.json"
    try:
        response = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(response['Body'].read().decode('utf-8'))
        return data
    except Exception as e:
        return {"error": str(e)}

@app.list_tools()
async def list_tools() -> list[Tool]:
    """사용 가능한 CMDB 도구 목록"""
    return [
        Tool(
            name="get_identity_policies",
            description="IAM, Organizations, Cognito 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD), 생략시 최신"}
                }
            }
        ),
        Tool(
            name="get_storage_policies",
            description="S3, EFS, FSx 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        ),
        Tool(
            name="get_compute_policies",
            description="EC2, Lambda, ECS 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        ),
        Tool(
            name="get_database_policies",
            description="RDS, DynamoDB 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        ),
        Tool(
            name="get_network_policies",
            description="VPC, CloudFront, Route53 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        ),
        Tool(
            name="get_security_policies",
            description="KMS, Secrets Manager, WAF 정책 조회",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        ),
        Tool(
            name="search_resources",
            description="리소스 검색 (이름, 타입, 태그 등)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색어"},
                    "category": {"type": "string", "description": "카테고리 (identity/storage/compute 등)"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_resource_summary",
            description="전체 리소스 요약 통계",
            inputSchema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "날짜 (YYYYMMDD)"}
                }
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """도구 실행"""
    date = arguments.get('date')
    
    if name == "get_identity_policies":
        data = load_cmdb_data("identity_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "get_storage_policies":
        data = load_cmdb_data("storage_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "get_compute_policies":
        data = load_cmdb_data("compute_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "get_database_policies":
        data = load_cmdb_data("database_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "get_network_policies":
        data = load_cmdb_data("network_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "get_security_policies":
        data = load_cmdb_data("security_policies", date)
        return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]
    
    elif name == "search_resources":
        query = arguments.get('query', '').lower()
        category = arguments.get('category', 'all')
        
        categories = ['identity_policies', 'storage_policies', 'compute_policies', 
                     'database_policies', 'network_policies', 'security_policies']
        
        if category != 'all':
            categories = [f"{category}_policies"]
        
        results = []
        for cat in categories:
            data = load_cmdb_data(cat, date)
            # 간단한 검색 로직
            if query in json.dumps(data).lower():
                results.append({cat: data})
        
        return [TextContent(type="text", text=json.dumps(results, indent=2, default=str))]
    
    elif name == "get_resource_summary":
        summary = {}
        categories = ['identity_policies', 'storage_policies', 'compute_policies', 
                     'database_policies', 'network_policies', 'security_policies']
        
        for cat in categories:
            data = load_cmdb_data(cat, date)
            summary[cat] = {
                "total_accounts": len(data.keys()) if isinstance(data, dict) else 0,
                "data_size": len(json.dumps(data))
            }
        
        return [TextContent(type="text", text=json.dumps(summary, indent=2))]
    
    return [TextContent(type="text", text="Unknown tool")]

async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
