import os
import math
import asyncio
import uuid
import httpx

from typing import Annotated, List, Set, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status, UploadFile, File
from fastapi.staticfiles import StaticFiles
from sqlmodel import select, func, SQLModel # func를 임포트
from sqlmodel.ext.asyncio.session import AsyncSession

from models import BlogArticle, ArticleCreate, ArticleUpdate, ArticleImage
from database import init_db, get_session

app = FastAPI(title="Blog Service")
USER_SERVICE_URL = os.getenv("USER_SERVICE_URL", "http://user_service:8001") # 기본값 추가 (Docker 환경 고려)

# 현재 작업 디렉토리 기준으로 STATIC_DIR 설정
# 개발 환경에서 프로젝트 루트에 static 폴더가 있다고 가정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(CURRENT_DIR, "static") # static 폴더가 main.py와 같은 레벨에 있을 경우
IMAGE_DIR = os.path.join(STATIC_DIR, "images")

os.makedirs(IMAGE_DIR, exist_ok=True) # 이미지 저장 폴더 생성
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

class PaginatedResponse(SQLModel):
    total: int
    page: int
    size: int
    pages: int
    items: List[dict] = []


@app.on_event("startup")
async def on_startup():
    await init_db()

# --- 게시글 생성 엔드포인트 ---
@app.post("/api/blog/articles", response_model=BlogArticle, status_code=status.HTTP_201_CREATED)
async def create_article(
    article_data: ArticleCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_id: Annotated[int, Header(alias="X-User-Id")],
):
    """새로운 블로그 게시글을 생성합니다."""
    new_article = BlogArticle.model_validate(article_data, update={"owner_id": x_user_id})
    session.add(new_article)
    await session.commit()
    await session.refresh(new_article)
    return new_article

# --- 게시글 이미지 업로드 엔드포인트 ---
@app.post("/api/blog/articles/{article_id}/upload-images", response_model=List[str])
async def upload_article_images(
    article_id: int,
    files: List[UploadFile],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_id: Annotated[int, Header(alias="X-User-Id")],
):
    """게시글에 여러 이미지를 업로드하고 파일명을 DB에 저장합니다."""
    db_article = await session.get(BlogArticle, article_id)
    if not db_article:
        raise HTTPException(status_code=404, detail="Article not found")
    if db_article.owner_id != x_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    saved_filenames = []
    for file in files:
        file_extension = os.path.splitext(file.filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        file_path = os.path.join(IMAGE_DIR, unique_filename)

        # 파일 저장
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        # DB에 이미지 정보 저장
        new_image = ArticleImage(image_filename=unique_filename, article_id=article_id)
        session.add(new_image)
        saved_filenames.append(unique_filename)

    await session.commit()
    return saved_filenames

# --- 특정 게시글 조회 엔드포인트 ---
@app.get("/api/blog/articles/{article_id}")
async def get_article(article_id: int, session: Annotated[AsyncSession, Depends(get_session)]):
    """특정 블로그 게시글의 상세 정보를 반환합니다."""
    article = await session.get(BlogArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    author_info = {}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{USER_SERVICE_URL}/api/users/{article.owner_id}")
            if resp.status_code == 200:
                author_info = resp.json()
    except Exception as e:
        print(f"Error fetching author info for owner_id {article.owner_id}: {e}")
        author_info = {"username": "Unknown"}

    image_query = select(ArticleImage.image_filename).where(ArticleImage.article_id == article_id)
    image_results = await session.exec(image_query)
    image_filenames = image_results.all()

    image_urls = [f"/static/images/{filename}" for filename in image_filenames]

    return {"article": article, "author": author_info, "image_urls": image_urls}

# --- 게시글 목록 조회 엔드포인트 ---
@app.get("/api/blog/articles", response_model=PaginatedResponse)
async def list_articles(
    session: Annotated[AsyncSession, Depends(get_session)],
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    owner_id: Optional[int] = None,
    tag: Optional[str] = None
):
    """블로그 게시글 목록을 페이지네이션하여 반환합니다."""
    offset = (page - 1) * size

    count_query = select(func.count(BlogArticle.id))
    articles_query = select(BlogArticle).order_by(BlogArticle.id.desc())

    if owner_id:
        count_query = count_query.where(BlogArticle.owner_id == owner_id)
        articles_query = articles_query.where(BlogArticle.owner_id == owner_id)

    if tag:
        count_query = count_query.where(BlogArticle.tags.like(f"%{tag}%"))
        articles_query = articles_query.where(BlogArticle.tags.like(f"%{tag}%"))

    total_result = await session.exec(count_query)
    total = total_result.one()

    paginated_query = articles_query.offset(offset).limit(size)
    articles_result = await session.exec(paginated_query)
    articles = articles_result.all()

    author_ids = {p.owner_id for p in articles}
    authors = {}
    if author_ids:
        try:
            async with httpx.AsyncClient() as client:
                tasks = [client.get(f"{USER_SERVICE_URL}/api/users/{uid}") for uid in author_ids]
                results = await asyncio.gather(*tasks)
                for resp in results:
                    if resp.status_code == 200:
                        data = resp.json()
                        authors[data['id']] = data.get('username', 'Unknown')
        except Exception as e:
            print(f"Error fetching authors: {e}")

    article_ids = [a.id for a in articles]
    thumbnails = {}
    if article_ids:
        image_query = select(ArticleImage).where(ArticleImage.article_id.in_(article_ids))
        image_results = await session.exec(image_query)
        for img in image_results.all():
            if img.article_id not in thumbnails:
                thumbnails[img.article_id] = f"/static/images/{img.image_filename}"

    items_with_details = []
    for article in articles:
        article_dict = article.model_dump()
        article_dict["author_username"] = authors.get(article.owner_id, "Unknown")
        article_dict["image_url"] = thumbnails.get(article.id)
        items_with_details.append(article_dict)

    return PaginatedResponse(
        total=total, page=page, size=size,
        pages=math.ceil(total / size), items=items_with_details
    )

# --- 모든 태그 조회 엔드포인트 ---
@app.get("/api/blog/tags", response_model=List[str])
async def get_all_tags(session: Annotated[AsyncSession, Depends(get_session)]):
    """모든 게시물의 태그를 수집하여 중복없이 반환합니다."""
    query = select(BlogArticle.tags).where(BlogArticle.tags != None)
    result = await session.exec(query)
    all_tags: Set[str] = set()

    for tags_str in result.all():
        if tags_str is not None:
            tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
            all_tags.update(tags)
    return sorted(list(all_tags))

# --- 인기 (최신) 게시글 조회 엔드포인트 ---
@app.get("/api/blog/popular-articles", response_model=List[BlogArticle])
async def get_popular_articles(session: Annotated[AsyncSession, Depends(get_session)]):
    """가장 최근에 작성된 블로그 게시글 4개를 반환합니다."""
    query = select(BlogArticle).order_by(BlogArticle.id.desc()).limit(4)
    result = await session.exec(query)
    popular_articles = result.all()
    return popular_articles

# --- 게시글 업데이트 엔드포인트 ---
@app.patch("/api/blog/articles/{article_id}", response_model=BlogArticle)
async def update_article(
    article_id: int,
    article_data: ArticleUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_id: Annotated[int, Header(alias="X-User-Id")],
):
    """특정 블로그 게시글의 내용을 업데이트합니다."""
    db_article = await session.get(BlogArticle, article_id)
    if not db_article:
        raise HTTPException(status_code=404, detail="Article not found")
    if db_article.owner_id != x_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = article_data.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(db_article, key, value)

    session.add(db_article)
    await session.commit()
    await session.refresh(db_article)
    return db_article

# --- 게시글 삭제 엔드포인트 ---
@app.delete("/api/blog/articles/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(
    article_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    x_user_id: Annotated[int, Header(alias="X-User-Id")],
):
    """특정 블로그 게시글을 삭제하고 연관된 이미지 파일 및 DB 기록을 삭제합니다."""
    db_article = await session.get(BlogArticle, article_id)
    if not db_article:
        raise HTTPException(status_code=404, detail="Article not found")
    if db_article.owner_id != x_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # 게시글에 연결된 모든 이미지 조회 및 삭제
    image_query = select(ArticleImage).where(ArticleImage.article_id == article_id)
    images_to_delete = (await session.exec(image_query)).all()
    for image in images_to_delete:
        file_path = os.path.join(IMAGE_DIR, image.image_filename)
        if os.path.exists(file_path):
            os.remove(file_path) # 실제 이미지 파일 삭제
        await session.delete(image) # DB에서 이미지 기록 삭제

    # 게시글 자체 삭제
    await session.delete(db_article)
    await session.commit()
    return