
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.meta_client import meta_call

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

RULES_PATH = Path(r"C:\Users\AcTivE\Desktop\manus_meta_server\comment_rules.json")
VERIFY_TOKEN = "my_verify_token_123"


def load_rules() -> List[Dict[str, Any]]:
    if not RULES_PATH.exists():
        return []
    import json
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def save_rules(rules: List[Dict[str, Any]]) -> None:
    import json
    RULES_PATH.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


@router.get("/meta")
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge) if hub_challenge and hub_challenge.isdigit() else (hub_challenge or "")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/meta")
async def receive_webhook(request: Request):
    payload = await request.json()

    rules = load_rules()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            comment_id = value.get("comment_id") or value.get("post_id")
            message = (value.get("message") or "").strip().lower()
            access_token = value.get("access_token")

            if not comment_id or not message or not access_token:
                continue

            for rule in rules:
                keyword = str(rule.get("keyword", "")).strip().lower()
                reply_message = rule.get("reply_message", "")
                hide_comment = bool(rule.get("hide_comment", False))

                if keyword and keyword in message:
                    if reply_message:
                        try:
                            meta_call("POST", f"{comment_id}/comments", access_token, data={"message": reply_message})
                        except Exception:
                            pass

                    if hide_comment:
                        try:
                            meta_call("POST", comment_id, access_token, data={"is_hidden": True})
                        except Exception:
                            pass

                    break

    return {"ok": True}


@router.get("/rules")
async def list_rules():
    return {"rules": load_rules()}


@router.post("/rules")
async def add_rule(body: dict):
    rules = load_rules()
    rules.append(body)
    save_rules(rules)
    return {"success": True, "rules": rules}


@router.delete("/rules")
async def clear_rules():
    save_rules([])
    return {"success": True, "rules": []}
