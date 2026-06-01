from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CommentAutomationManageRequest(BaseModel):
    action: Literal[
        "list_pages",
        "list_posts",
        "subscribe_page",
        "create_rule",
        "list_rules",
        "enable_rule",
        "disable_rule",
        "delete_rule",
        "list_logs",
    ]
    tenant_id: str | None = None
    page_id: str | None = None
    post_id: str | None = None
    rule_id: str | None = None
    keyword: str | None = None
    match_mode: Literal["all_comments", "contains_keyword"] = "all_comments"
    public_reply_message: str | None = Field(default=None, max_length=2000)
    private_reply_message: str | None = Field(default=None, max_length=2000)
    hide_comment: bool = False
    limit: int = Field(default=30, ge=1, le=100)

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.action in {"list_posts", "subscribe_page", "create_rule"} and not self.page_id:
            raise ValueError("page_id is required for this action.")
        if self.action == "create_rule":
            if not self.post_id:
                raise ValueError("post_id is required for create_rule.")
            if not (self.public_reply_message or self.private_reply_message or self.hide_comment):
                raise ValueError("Add a public reply, a private reply, or hide_comment.")
            if self.match_mode == "contains_keyword" and not str(self.keyword or "").strip():
                raise ValueError("keyword is required when match_mode is contains_keyword.")
        if self.action in {"enable_rule", "disable_rule", "delete_rule"} and not self.rule_id:
            raise ValueError("rule_id is required for this action.")
        return self
