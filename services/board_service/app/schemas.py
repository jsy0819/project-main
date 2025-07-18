from typing import Optional, List
from sqlmodel import Field, SQLModel

class PaginatedResponse(SQLModel):
  total: int
  page: int
  size: int
  pages: int
  items: List[dict] = []