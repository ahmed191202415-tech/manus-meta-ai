from app.main import openapi_gpt_schema


def test_gpt_schema_exposes_dynamic_meta_query_as_primary_meta_read_tool():
    schema = openapi_gpt_schema()

    assert "/meta/query" in schema["paths"]
    assert "/meta/request" in schema["paths"]
    assert "/meta/smart_insights" not in schema["paths"]
    assert schema["paths"]["/meta/query"]["post"]["summary"] == "Dynamic Meta Graph read"
    assert schema["paths"]["/meta/request"]["post"]["summary"] == "Dynamic Meta Graph write"
    assert "use /meta/query as the primary dynamic Meta Graph read tool" in schema["info"]["description"]
    assert "Use /meta/request only when the user explicitly asks" in schema["info"]["description"]


def test_gpt_schema_stays_within_chatgpt_actions_operation_limit():
    schema = openapi_gpt_schema()
    operations = [
        method
        for path_item in schema["paths"].values()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    ]

    assert len(operations) <= 30
