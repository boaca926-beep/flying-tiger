"""Tests for app.py — pure functions only, no Streamlit runtime or real DB needed."""
import os

# Set dummy env vars BEFORE importing app, so agent.py doesn't blow up
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("GROQ_API_KEY", "dummy")
os.environ.setdefault("LLM_MODEL", "openai/gpt-oss-120b")

from app import make_message  # noqa: E402


def test_make_message_has_required_keys():
    msg = make_message("user", content="hello")
    assert msg["role"] == "user"
    assert msg["content"] == "hello"
    assert "id" in msg


def test_make_message_role_is_preserved():
    assert make_message("assistant")["role"] == "assistant"
    assert make_message("user")["role"] == "user"


def test_make_message_ids_are_8_char_hex():
    msg = make_message("user", content="x")
    msg_id = msg["id"]
    assert len(msg_id) == 8
    int(msg_id, 16)  # raises ValueError if not valid hex


def test_make_message_ids_are_unique():
    ids = {make_message("user", content=str(i))["id"] for i in range(100)}
    assert len(ids) == 100


def test_make_message_extra_fields_pass_through():
    msg = make_message("assistant", content="hi", products=[{"name": "mug"}])
    assert msg["products"] == [{"name": "mug"}]
    assert msg["content"] == "hi"