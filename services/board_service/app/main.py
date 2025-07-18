import os
from pathlib import Path
import uuid
from typing import List, Optional
import aiofiles

from fastapi import FastAPI, Depends, HTTPException, status, Form, UploadFile, File, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession
from datetime import datetime
from zoneinfo import ZoneInfo
from schemas import PaginatedResponse

# database.py에서 DB 관련 함수 임포트
from database import get_session, init_db

# models.py에서 모델 및 헬퍼 함수 임포트
from models import Post, Comment, PostFile, hash_password, verify_password, SEOUL_TZ, PostBase, CommentBase, PostFileBase

# 환경 변수 로드 (database.py에서도 로드하지만, main에서도 필요할 수 있으므로 추가)
from dotenv import load_dotenv
load_dotenv()

# Redis 클라이언트 임포트 (redis.asyncio 사용)
import redis.asyncio as redis # <--- Redis 임포트

# --- 설정 (Configuration) ---
app = FastAPI(title="Board Service with MySQL")

# CORS 설정: 프론트엔드 도메인에 맞춰 조정
origins = [
    "http://localhost",
    "http://localhost:80",
    "http://localhost:8000", # FastAPI 직접 접근 (개발 시)
    "http://localhost:8080", # API Gateway 포트 (개발 시)
    # 실제 배포 시에는 'http://your_frontend_domain.com' 등으로 설정
    "*" # 모든 도메인 허용 (개발 편의상, 실제 서비스에서는 특정 도메인만 허용하는 것이 보안에 좋음)
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # 모든 HTTP 메서드 (GET, POST, PUT, DELETE, OPTIONS) 허용
    allow_headers=["*"], # 모든 헤더 허용
)

# 파일 업로드 디렉토리 설정 (Docker 컨테이너 내부 경로)
UPLOAD_DIR = Path("/app/uploads")

# Redis 클라이언트 변수 초기화
redis_client: Optional[redis.Redis] = None # <--- Redis 클라이언트 변수 선언

# --- 앱 시작 시 실행될 함수 ---
@app.on_event("startup")
async def on_startup():
    print("Initializing database and upload directory...")
    await init_db() # 데이터베이스 테이블 생성
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True) # 업로드 폴더가 없으면 생성
    print("Database initialized and upload directory created.")

    # Redis 클라이언트 초기화
    global redis_client # <--- 전역 변수임을 명시
    REDIS_URL = os.getenv("REDIS_URL")
    if not REDIS_URL:
        raise ValueError("REDIS_URL 환경 변수가 설정되지 않았습니다.")
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.ping()
        print("Redis 연결 성공!")
    except redis.exceptions.ConnectionError as e:
        print(f"Redis 연결 실패: {e}")
        # Redis 연결이 필수적이라면 여기서 애플리케이션 시작을 중단할 수 있습니다.
        raise HTTPException(status_code=500, detail="Redis connection failed")


@app.on_event("shutdown")
async def on_shutdown():
    # Redis 연결 종료
    if redis_client:
        await redis_client.aclose()
        print("Redis 연결 종료.")

# --- API 엔드포인트 ---

## 게시글 (Posts) 관련 엔드포인트

### 게시글 생성
@app.post("/api/board/posts/", response_model=Post)
async def create_post(
    title: str = Form(...),
    content: str = Form(...),
    nickname: str = Form(...),
    password: str = Form(...),
    files: Optional[List[UploadFile]] = File(None), # 파일은 선택 사항
    session: AsyncSession = Depends(get_session)
):
    new_post = Post(
        title=title,
        content=content,
        nickname=nickname,
        created_at=datetime.now(SEOUL_TZ),
        updated_at=datetime.now(SEOUL_TZ)
    )
    new_post.set_password(password) # 비밀번호 해싱 및 설정

    session.add(new_post)
    await session.commit()
    await session.refresh(new_post) # id를 포함한 최신 정보 로드

    if files:
        for file in files:
            if file.filename: # 파일명이 있는 경우에만 처리
                file_extension = file.filename.split(".")[-1] if "." in file.filename else ""
                unique_filename = f"{uuid.uuid4()}.{file_extension}" if file_extension else str(uuid.uuid4())
                file_path_on_server = UPLOAD_DIR / unique_filename

                async with aiofiles.open(file_path_on_server, "wb") as f:
                    content_bytes = await file.read()
                    await f.write(content_bytes)

                post_file = PostFile(
                    filename=file.filename,
                    filepath=unique_filename,
                    mimetype=file.content_type,
                    post_id=new_post.id
                )
                session.add(post_file)
        await session.commit()
        await session.refresh(new_post) # 파일 관계가 로드되도록 다시 refresh

    return new_post

### 게시글 목록 조회
@app.get("/api/board/posts/", response_model=PaginatedResponse)
async def get_all_posts(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    size: int = Query(10, ge=1, le=100, description="페이지당 항목 수"),
    session: AsyncSession = Depends(get_session)
):
    total_statement = select(Post)
    total_count_result = await session.exec(total_statement)
    total_items = len(total_count_result.all())

    total_pages = (total_items + size - 1) // size if total_items > 0 else 0

    skip = (page - 1) * size

    statement = select(Post).order_by(Post.created_at.desc()).offset(skip).limit(size)
    posts = await session.exec(statement)
    items_on_page = posts.all()

    # Redis에 있는 최신 조회수를 반영하여 응답 (선택 사항)
    # 실제로는 워커가 주기적으로 DB에 동기화하므로, 여기서는 DB 데이터만 반환해도 무방합니다.
    # 하지만 실시간으로 Redis 조회수를 보여주고 싶다면 아래 로직 추가
    updated_items = []
    if redis_client:
        for post in items_on_page:
            redis_views = await redis_client.get(f"views:post:{post.id}")
            if redis_views:
                post.views = int(redis_views) # Redis에 있는 조회수로 업데이트
            updated_items.append(post)
    else:
        updated_items = items_on_page


    return PaginatedResponse(
        total=total_items,
        page=page,
        size=size,
        pages=total_pages,
        items=[item.model_dump() for item in updated_items]
    )

### 특정 게시글 조회 (조회수 Redis 증가 및 큐에 추가)
@app.get("/api/board/posts/{post_id}", response_model=Post)
async def get_post_by_id(post_id: int, session: AsyncSession = Depends(get_session)):
    statement = select(Post).where(Post.id == post_id)
    post = await session.exec(statement)
    found_post = post.first()

    if not found_post:
        raise HTTPException(status_code=404, detail="Post not found")

    # --- Redis 조회수 증가 및 동기화 큐에 추가 ---
    if redis_client:
        redis_key = f"views:post:{post_id}"
        # Redis 조회수 1 증가 (없으면 0에서 시작)
        current_redis_views = await redis_client.incr(redis_key)
        # 동기화가 필요한 게시물 ID를 큐에 추가 (Sorted Set 사용, score는 현재 시간 또는 아무 값)
        await redis_client.zadd("view_sync_queue", {str(post_id): datetime.now().timestamp()}) # 현재 시간을 score로 사용

        # DB 모델의 조회수를 Redis에서 가져온 최신 값으로 업데이트하여 반환
        found_post.views = current_redis_views
        # DB에는 바로 커밋하지 않음 (워커가 처리할 것임)
    else:
        # Redis 연결이 안 되어있다면 기존 DB 직접 업데이트 로직 유지 (폴백)
        found_post.views += 1
        session.add(found_post)
        await session.commit()
        await session.refresh(found_post)


    return found_post

### 게시글 수정
@app.put("/api/board/posts/{post_id}", response_model=Post)
async def update_post(
    post_id: int,
    password: str = Form(...), # 비밀번호는 필수로 받음
    title: Optional[str] = Form(None),
    content: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session)
):
    statement = select(Post).where(Post.id == post_id)
    post = await session.exec(statement)
    found_post = post.first()

    if not found_post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not verify_password(password, found_post.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    if title is not None:
        found_post.title = title
    if content is not None:
        found_post.content = content
    found_post.updated_at = datetime.now(SEOUL_TZ)

    session.add(found_post)
    await session.commit()
    await session.refresh(found_post)
    return found_post

### 게시글 삭제
@app.delete("/api/board/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: int,
    password: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    statement = select(Post).where(Post.id == post_id)
    post = await session.exec(statement)
    found_post = post.first()

    if not found_post:
        raise HTTPException(status_code=404, detail="Post not found")

    if not verify_password(password, found_post.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    # 관련 파일 삭제 (실제 파일 시스템에서도 삭제)
    for file_obj in found_post.files:
        file_path_on_server = UPLOAD_DIR / file_obj.filepath
        if file_path_on_server.exists():
            os.remove(file_path_on_server)
    
    session.delete(found_post)
    await session.commit()

    # 게시글 삭제 시 Redis의 조회수 캐시 및 큐에서도 제거 (선택 사항)
    if redis_client:
        await redis_client.delete(f"views:post:{post_id}")
        await redis_client.zrem("view_sync_queue", str(post_id))

    return

## 댓글 (Comments) 관련 엔드포인트

### 댓글 생성
@app.post("/api/board/posts/{post_id}/comments/", response_model=Comment)
async def create_comment(
    post_id: int,
    nickname: str = Form(...),
    password: str = Form(...),
    content: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    post_statement = select(Post).where(Post.id == post_id)
    post_result = await session.exec(post_statement)
    found_post = post_result.first()

    if not found_post:
        raise HTTPException(status_code=404, detail="Post not found")

    new_comment = Comment(
        nickname=nickname,
        content=content,
        post_id=post_id,
        created_at=datetime.now(SEOUL_TZ)
    )
    new_comment.set_password(password)

    session.add(new_comment)
    await session.commit()
    await session.refresh(new_comment)
    return new_comment

### 댓글 수정
@app.put("/api/board/comments/{comment_id}", response_model=Comment)
async def update_comment(
    comment_id: int,
    password: str = Form(...),
    content: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    statement = select(Comment).where(Comment.id == comment_id)
    comment_result = await session.exec(statement)
    found_comment = comment_result.first()

    if not found_comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if not verify_password(password, found_comment.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    found_comment.content = content
    session.add(found_comment)
    await session.commit()
    await session.refresh(found_comment)
    return found_comment

### 댓글 삭제
@app.delete("/api/board/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    password: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    statement = select(Comment).where(Comment.id == comment_id)
    comment_result = await session.exec(statement)
    found_comment = comment_result.first()

    if not found_comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    if not verify_password(password, found_comment.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    session.delete(found_comment)
    await session.commit()
    return

## 파일 (Files) 관련 엔드포인트

### 파일 다운로드
@app.get("/api/board/files/{file_id}")
async def download_file(file_id: int, session: AsyncSession = Depends(get_session)):
    statement = select(PostFile).where(PostFile.id == file_id)
    file_record_result = await session.exec(statement)
    found_file = file_record_result.first()

    if not found_file:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = UPLOAD_DIR / found_file.filepath
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on server")

    return FileResponse(path=str(file_path), filename=found_file.filename, media_type=found_file.mimetype)