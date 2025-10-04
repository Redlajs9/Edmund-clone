from pydantic import BaseModel
from typing import List, Dict, Optional

class ChatRequest(BaseModel):
    question: str

class ChatResponse(BaseModel):
    status: str
    message: Optional[str] = None
    answer: Optional[str] = None
    missing: List[str] = []
    why_needed: Dict[str, str] = {}
    how_to_connect_next: List[str] = []
