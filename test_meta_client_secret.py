from app.core.meta_client import appsecret_proof


def test_appsecret_proof_does_not_use_global_secret_for_direct_tokens():
    assert appsecret_proof("token-without-tenant-secret") is None


def test_appsecret_proof_uses_explicit_secret():
    assert appsecret_proof("token", app_secret="secret")
