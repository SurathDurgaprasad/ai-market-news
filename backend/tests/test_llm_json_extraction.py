import pytest
from app.core.providers.llm import extract_json_object

def test_extract_json_with_trailing_curly():
    # If the LLM generates some prose that contains a closing brace after the JSON
    text = 'Here is your output:\n{"key": "value"}\nNote: this is a test {with braces}.'
    
    # We expect extract_json_object to return ONLY the valid JSON object
    # If it grabs the first { and the very last }, it will fail to parse later.
    extracted = extract_json_object(text)
    
    import json
    try:
        json.loads(extracted)
    except json.JSONDecodeError:
        pytest.fail("extract_json_object returned invalid JSON due to trailing braces in prose")

def test_extract_json_normal_prose():
    text = 'Here is your output:\n{"key": "value"}\nHave a nice day!'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"key": "value"}

def test_extract_json_braces_in_strings():
    text = '{"key": "value with { brace", "key2": "value with } brace"}'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"key": "value with { brace", "key2": "value with } brace"}

def test_extract_json_escaped_quotes_and_backslashes():
    text = '{"key": "value with \\" quote", "key2": "value with \\\\ backslash"}'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"key": 'value with " quote', "key2": 'value with \\ backslash'}

def test_extract_json_nested_objects_and_arrays():
    text = '{"key": {"nested": [1, 2, {"deep": 3}]}}'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"key": {"nested": [1, 2, {"deep": 3}]}}

def test_extract_json_unicode_and_markdown_fences():
    text = '```json\n{"key": "value \u2728"}\n```'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"key": "value ✨"}

def test_extract_json_multiple_objects_returns_first():
    text = '{"first": 1}\n\n{"second": 2}'
    extracted = extract_json_object(text)
    import json
    assert json.loads(extracted) == {"first": 1}

def test_extract_json_malformed_first_object_fails():
    # If the first object is malformed, it should raise an error, or if we want, it should recover the second?
    # extract_json_object strictly returns the first balanced object. If it's syntactically balanced but invalid JSON, json.loads will fail.
    # But if the braces are unbalanced, it might consume the second object to balance!
    text = 'Here is { malformed string }\n\n{"valid": true}'
    
    # Actually, our current extract_json_object just counts '{' and '}'. 
    # 'Here is { malformed string }' has balanced braces. So it will return '{ malformed string }'.
    # This is expected behavior for a dumb brace extractor. It is up to Pydantic to reject it.
    extracted = extract_json_object(text)
    assert extracted == '{ malformed string }'

def test_extract_json_truncated():
    text = '{"key": "value"'
    with pytest.raises(ValueError, match="no JSON object in model output"):
        extract_json_object(text)
