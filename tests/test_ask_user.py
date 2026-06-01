import json
import pytest

from nova.tools.ask_user import ask_user
from nova.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_ask_user_single_question():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "header": "Current City",
            "question": "Please tell me which city you want the weather for.",
            "input_type": "text",
            "options": [],
        }
    ])

    assert result.requires_input is True
    payload = json.loads(result.content)
    assert payload == {
        "questions": [{
            "id": "q1",
            "header": "Current City",
            "question": "Please tell me which city you want the weather for.",
            "input_type": "text",
            "options": [],
            "multiple": False,
            "required": True,
        }]
    }


@pytest.mark.asyncio
async def test_ask_user_select_question():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "header": "Framework",
            "question": "Choose a framework",
            "input_type": "select",
            "options": [
                {"label": "Textual", "description": "Build TUI apps"},
                {"label": "React", "description": "Build web apps"},
            ],
            "multiple": True,
        }
    ])

    payload = json.loads(result.content)
    q = payload["questions"][0]
    assert q["input_type"] == "select"
    assert q["options"] == [
        {"label": "Textual", "description": "Build TUI apps"},
        {"label": "React", "description": "Build web apps"},
    ]
    assert q["multiple"] is True
    assert q["required"] is True


@pytest.mark.asyncio
async def test_ask_user_confirm_question():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "question": "Deploy now?",
            "input_type": "confirm",
            "options": [],
        }
    ])

    payload = json.loads(result.content)
    assert payload["questions"][0]["input_type"] == "confirm"


@pytest.mark.asyncio
async def test_ask_user_multiple_questions():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "header": "Name",
            "question": "What is your name?",
            "input_type": "text",
            "options": [],
        },
        {
            "id": "q2",
            "question": "Framework?",
            "input_type": "select",
            "options": [{"label": "A", "description": "Opt A"}, {"label": "B", "description": "Opt B"}],
        },
    ])

    payload = json.loads(result.content)
    assert len(payload["questions"]) == 2
    assert payload["questions"][0]["id"] == "q1"
    assert payload["questions"][1]["id"] == "q2"


@pytest.mark.asyncio
async def test_ask_user_sanitizes_bad_input_type():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "question": "Test?",
            "input_type": "invalid",
            "options": [],
        }
    ])

    payload = json.loads(result.content)
    assert payload["questions"][0]["input_type"] == "text"


@pytest.mark.asyncio
async def test_ask_user_auto_id_when_missing():
    result = await ask_user(questions=[
        {
            "question": "Q1?",
            "input_type": "text",
            "options": [],
        },
        {
            "question": "Q2?",
            "input_type": "text",
            "options": [],
        },
    ])

    payload = json.loads(result.content)
    assert payload["questions"][0]["id"] == "q0"
    assert payload["questions"][1]["id"] == "q1"


def test_ask_user_schema_describes_questions():
    registry = ToolRegistry()
    registry.register_by_metadata("ask_user")

    schema = registry.get_schema()[0]["function"]
    properties = schema["parameters"]["properties"]
    assert "questions" in properties
    assert schema["parameters"]["required"] == ["questions"]


@pytest.mark.asyncio
async def test_ask_user_strips_blank_options():
    result = await ask_user(questions=[
        {
            "id": "q1",
            "question": "Pick one",
            "input_type": "select",
            "options": [
                {"label": "", "description": "empty"},
                {"label": "Valid", "description": "good"},
            ],
        }
    ])

    payload = json.loads(result.content)
    assert len(payload["questions"][0]["options"]) == 1
    assert payload["questions"][0]["options"][0]["label"] == "Valid"
