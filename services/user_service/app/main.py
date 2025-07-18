import os
import uuid
from typing import Annotated, Optional
from fastapi import FastAPI, status, Response, Depends, HTTPException, Cookie, UploadFile, File, Header
from fastapi.staticfiles import StaticFiles
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from redis.asyncio import Redis

from models import User, UserCreate, UserPublic, Userlogin, UserUpdate, UpdatePassword
from database import init_db, get_session
from redis_client import get_redis
from auth import get_password_hash, create_session, verify_password, get_user_id_from_session, delete_session
app = FastAPI(title="User Service")

STATIC_DIR = "/app/static"
PROFILE_IMAGE_DIR = f"{STATIC_DIR}/profiles"
os.makedirs(PROFILE_IMAGE_DIR, exist_ok =True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def create_user_public(user: User) -> UserPublic:
    
    image_url = f"/static/profiles/{user.profile_image_filename}" if user.profile_image_filename else "https://www.w3schools.com/w3images/avatar_g.jpg"
    user_dict = user.model_dump()
    user_dict["profile_image_url"] = image_url
    return UserPublic.model_validate(user_dict)
    '''
    if user.profile_image_filename:
        image_url = f"/static/profiles/{user.profile_image_filename}" 
    else:
        image_url = "https://www.w3schools.com/w3images/avatar_g.jpg"
    '''

async def get_current_user_id(
    session_id: Annotated[str | None, Cookie()] = None,
    redis: Annotated[Redis, Depends(get_redis)] = None,
) -> int:
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id_str = await get_user_id_from_session(redis, session_id)
    if not user_id_str:
        raise HTTPException(status_code=401, detail="Invalid session")
    return int(user_id_str)

@app.on_event("startup")
async def on_startup():
    await init_db()

@app.get("/")
def health_check():
    return {"status":"User service running"}

@app.post('/api/auth/register', response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register_user(
    response: Response,
    user_data: UserCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)]
):
    #username='111' email='3R#SDAF@DSAF.COM' password='111' bio='FDSDFSA '
    #print(user_data)
    statement = select(User).where(User.email==user_data.email)
    exist_user_result = await session.exec(statement)
    #print(user_data)
    if exist_user_result.one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="이미 사용중인 이메일 입니다.")
    
    hashed_password = get_password_hash(user_data.password)
    new_user = User.model_validate(user_data, update={"hashed_password": hashed_password})
    
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)
    if not new_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="데이터 저장에 실패 했습니다.")
    session_id = await create_session(redis, new_user.id)
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax", max_age=3600, path="/")

    return create_user_public(new_user)
    
@app.post("/api/auth/login")
async def login(
    response: Response,
    user_data: Userlogin,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)]
):
    
    statement = select(User).where(User.email==user_data.email)
    
    user_result = await session.exec(statement)
    
    user = user_result.one_or_none()
    
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="이메일 또는 비밀번호가 틀립니다.")
    if user.id is not None:
        session_id = await create_session(redis, user.id)
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="세션 번호가 저장되지 않았습니다.")
    response.set_cookie(key="session_id", value=session_id, httponly=True, samesite="lax", max_age=3600, path="/")
    return {"message":"Login 성공!"}
#Strict  Lax  None

@app.get("/api/auth/me", response_model=UserPublic)
async def get_current_user(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    session_id: Annotated[Optional[str], Cookie()] = None
):
    
    if not session_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    user_id = await get_user_id_from_session(redis, session_id)
    
    if not user_id:
        response.delete_cookie("session_id", path="/")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found redis session")
    
    user = await session.get(User, int(user_id))
    
    if not user:
        response.delete_cookie("session_id", path="/")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    
    return create_user_public(user)

@app.post("/api/auth/logout")
async def logout(
    response: Response,
    redis: Annotated[Redis, Depends(get_redis)],
    session_id: Annotated[Optional[str], Cookie()] = None
):
    if session_id:
        await delete_session(redis, session_id)
    response.delete_cookie("session_id", path="/")
    return {"message": "Logout 성공"}

@app.get("/api/users/{user_id}", response_model=UserPublic)
async def get_user_by_id(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)]
):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    
    return create_user_public(user)

@app.patch("/api/users/me", response_model=UserPublic)
async def update_my_profile(
    user_data: UserUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id: Annotated[int, Depends(get_current_user_id)],
):
    """로그인된 사용자의 프로필(이메일, 자기소개) 수정"""
    db_user = await session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # 제공된 데이터만 업데이트
    update_data = user_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
    
    await session.commit()
    await session.refresh(db_user)
    return create_user_public(db_user)
    
    
@app.post("/api/users/me/upload-image", response_model=UserPublic)
async def upload_my_profile_image(
    session: Annotated[AsyncSession, Depends(get_session)],
    user_id : Annotated[int, Depends(get_current_user_id)],
    file: UploadFile
):
    db_user = await session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자가 없습니다.")
    
    file_extension = os.path.splitext(file.filename)[1]
    unique_filenam = f"{uuid.uuid4()}{file_extension}"
    file_path = os.path.join(PROFILE_IMAGE_DIR, unique_filenam)
    
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())
        
    db_user.profile_image_filename = unique_filenam
    await session.commit()
    await session.refresh(db_user)
    return create_user_public(db_user)
    
@app.post("/api/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    password_data: UpdatePassword,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    user_id: Annotated[int, Depends(get_current_user_id)],
    session_id: Annotated[Optional[str], Cookie()] = None
):
    db_user = await session.get(User, user_id)
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="사용자가 없습니다.")
    
    if not verify_password(password_data.current_password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="비밀번호가 다릅니다.")
    
    db_user.hashed_password = get_password_hash(password_data.new_password)
    await session.commit()

    if session_id:
        await delete_session(redis, session_id)
        
    return Response(status_code=status.HTTP_204_NO_CONTENT)