from itsdangerous import BadSignature, URLSafeSerializer

from app.config import SESSION_SECRET


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(SESSION_SECRET, salt="gpt-oauth-return")


def encode_gpt_oauth_state(client_id: str, redirect_uri: str, state: str = "") -> str:
    return _serializer().dumps({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    })


def decode_gpt_oauth_state(value: str | None) -> dict:
    if not value:
        return {}
    try:
        payload = _serializer().loads(value)
    except BadSignature:
        return {}
    return payload if isinstance(payload, dict) else {}
