from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel, Relationship
from zoneinfo import ZoneInfo
from passlib.context import CryptContext
from sqlalchemy import Column, TEXT

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SEOUL_TZ = ZoneInfo("Asia/Seoul")

def hash_password(password: str) -> str:
    """주어진 비밀번호를 해싱합니다."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """평문 비밀번호와 해싱된 비밀번호를 비교합니다."""
    return pwd_context.verify(plain_password, hashed_password)

# 게시글 모델
class PostBase(SQLModel):
    title: str = Field(index=True)
    content: str = Field(sa_column=Column(TEXT))
    nickname: str = Field(max_length=50)
    password: str = Field(max_length=100)
    views: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(SEOUL_TZ))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(SEOUL_TZ))

class Post(PostBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    files: List["PostFile"] = Relationship(back_populates="post")
    comments: List["Comment"] = Relationship(back_populates="post")

    def set_password(self, plain_password: str):
        """평문 비밀번호를 받아 해싱하여 이 모델 인스턴스의 password 필드에 저장합니다."""
        self.password = hash_password(plain_password)

# 댓글 모델 (새로 추가)
class CommentBase(SQLModel):
    post_id: int = Field(foreign_key="post.id")
    content: str = Field(sa_column=Column(TEXT))
    nickname: str = Field(max_length=50)
    password: str = Field(max_length=100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(SEOUL_TZ))

class Comment(CommentBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post: Optional[Post] = Relationship(back_populates="comments")

    def set_password(self, plain_password: str):
        """평문 비밀번호를 받아 해싱하여 이 모델 인스턴스의 password 필드에 저장합니다."""
        self.password = hash_password(plain_password)

# PostFile 모델은 기존과 동일하게 유지
class PostFileBase(SQLModel):
    filename: str
    filepath: str
    mimetype: str
    post_id: Optional[int] = Field(default=None, foreign_key="post.id")

class PostFile(PostFileBase, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post: Optional[Post] = Relationship(back_populates="files")