from config.observability import scrub_pii


def test_scrub_pii_redacts_sensitive_keys_and_emails():
    event = {
        "event": "login for jane.doe@example.com failed",
        "password": "hunter2",
        "api_key": "sk_live_123",
        "Authorization": "Bearer abc",
        "date_of_birth": "2010-01-01",
        "user_id": "42",
    }
    scrubbed = scrub_pii(None, "info", event)
    assert scrubbed["event"] == "login for [EMAIL] failed"
    assert scrubbed["password"] == "[REDACTED]"
    assert scrubbed["api_key"] == "[REDACTED]"
    assert scrubbed["Authorization"] == "[REDACTED]"
    assert scrubbed["date_of_birth"] == "[REDACTED]"
    assert scrubbed["user_id"] == "42"
