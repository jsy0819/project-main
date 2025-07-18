"""
import os # 운영 체제와 상호작용하기 위한 모듈 (환경 변수 접근 등)
import math # 수학 연산을 위한 모듈 (현재 코드에서는 직접 사용되지 않음)
import asyncio # 비동기 프로그래밍을 위한 모듈
from typing import Annotated, List, Optional # 타입 힌트를 위한 모듈 (Annotated는 FastAPI에서 의존성 주입 시 추가 정보 제공, List는 목록, Optional은 값이 있을 수도 없을 수도 있음)
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status, Response # FastAPI 프레임워크의 핵심 구성 요소들 임포트
                                                                               # - FastAPI: 웹 애플리케이션 객체
                                                                               # - Depends: 의존성 주입
                                                                               # - HTTPException: HTTP 에러 발생
                                                                               # - Header: HTTP 헤더에서 값 가져오기
                                                                               # - Query: 쿼리 파라미터에서 값 가져오기
                                                                               # - status: HTTP 상태 코드
                                                                               # - Response: HTTP 응답 객체
from sqlmodel import select, func, SQLModel # SQLModel 라이브러리의 핵심 구성 요소들 임포트
                                            # - select: 데이터 조회 쿼리 생성
                                            # - func: SQL 함수 사용 (예: COUNT)
                                            # - SQLModel: ORM 모델 기본 클래스
from sqlmodel.ext.asyncio.session import AsyncSession # SQLModel의 비동기 세션 클래스
import httpx # 비동기 HTTP 클라이언트 (다른 서비스와 통신할 때 사용)
import redis.asyncio as redis # 비동기 Redis 클라이언트 (캐싱 등에 사용)

from database import init_db, get_session # 'database.py' 파일에서 데이터베이스 초기화 및 세션 가져오는 함수 임포트
from redis_client import get_redis # 'redis_client.py' 파일에서 Redis 클라이언트 가져오는 함수 임포트
from models import Post # 'models.py' 파일에서 'Post' 모델 임포트 (게시글 모델)

app = FastAPI(title="Board Service") # FastAPI 애플리케이션 객체를 생성하고, API 문서에 표시될 제목을 "Board Service"로 설정합니다.
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL") # 환경 변수에서 사용자 서비스의 URL을 가져옵니다. (현재는 비로그인 게시판이므로 사용되지 않을 수 있지만, 마이크로서비스 구조에서는 필요)

@app.on_event("startup") # FastAPI 앱이 시작될 때 실행될 이벤트를 등록합니다.
async def on_startup(): # 앱 시작 시 실행될 비동기 함수를 정의합니다.
    await init_db() # 'database.py'의 'init_db' 함수를 호출하여 데이터베이스 테이블을 생성하고 초기화합니다.
"""