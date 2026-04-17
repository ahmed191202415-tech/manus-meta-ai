
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field


class PagePostCreateRequest(BaseModel):
    page_id: str
    message: Optional[str] = None
    link: Optional[str] = None
    published: Optional[bool] = True
    scheduled_publish_time: Optional[str] = None
    attached_media: Optional[List[Dict[str, Any]]] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class CommentReplyRequest(BaseModel):
    message: str
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class CommentHideRequest(BaseModel):
    is_hidden: bool = True


class ObjectDeleteRequest(BaseModel):
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class CommentRuleRequest(BaseModel):
    keyword: str
    reply_message: str
    hide_comment: bool = False
