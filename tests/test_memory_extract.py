from unittest.mock import MagicMock
from codag.memory.extract import extract_facts_from_user_message, is_sensitive


def test_sensitive_data_filter():
    # Passwords and API keys must be flagged
    assert is_sensitive("My api_key = sk-1234567890abcdef1234567890") is True
    assert is_sensitive("password: supersecretpassword123") is True
    assert is_sensitive("Here is my secret token: ghp_123456789012345678901234567890123456") is True
    assert is_sensitive("-----BEGIN RSA PRIVATE KEY-----\nMIIEowI...") is True
    assert is_sensitive("My credit card is 4111-2222-3333-4444") is True
    assert is_sensitive("My SSN is 000-12-3456") is True

    # Normal user preferences must NOT be flagged
    assert is_sensitive("I prefer Python 3.12 and use VS Code") is False
    assert is_sensitive("My Mac Mini has 16GB RAM") is False


def test_user_only_extraction_security():
    # Attempting extraction on sensitive or trivial messages yields empty
    assert extract_facts_from_user_message("My password is secret123") == []
    assert extract_facts_from_user_message("Hello there") == []

    # Valid preference statement with mocked LLM
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.message.content = '[{"key": "editor", "value": "prefers VS Code", "category": "preference"}]'
    mock_llm.chat.return_value = mock_resp

    facts = extract_facts_from_user_message("I prefer to use VS Code for editing", llm=mock_llm)
    assert len(facts) == 1
    assert facts[0]["key"] == "editor"
    assert facts[0]["value"] == "prefers VS Code"
