import json
import pytest

from nova.tools.ask_user import ask_user
from nova.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_ask_user_renders_input_type():
    result = await ask_user(
        header="Current City",
        question="Please tell me which city you want the weather for, such as Beijing or Shanghai.",
        input_type="text",
        options=[
            {
                "label": "Enter city",
                "description": "Tell me the city you are currently in",
            }
        ],
    )

    assert result.requires_input is True
    payload = json.loads(result.content)
    assert payload["question"]["input_type"] == "text"
    assert payload["question"]["options"] == []


@pytest.mark.asyncio
async def test_ask_user_normalizes_select_question_payload():
    result = await ask_user(
        header="Current City",
        question="Please choose a city",
        input_type="select",
        options=[
            {"label": "Beijing", "description": "Capital", "extra": "ignored"},
            {"label": "Shanghai", "description": "Municipality"},
        ],
        multiple=True,
    )

    payload = json.loads(result.content)

    assert payload == {
        "question": {
            "header": "Current City",
            "question": "Please choose a city",
            "input_type": "select",
            "options": [
                {"label": "Beijing", "description": "Capital"},
                {"label": "Shanghai", "description": "Municipality"},
            ],
            "multiple": True,
        }
    }


@pytest.mark.asyncio
async def test_ask_user_allows_missing_header():
    result = await ask_user(
        question="Please choose a city",
        input_type="select",
        options=[
            {"label": "Beijing", "description": "Capital"},
        ],
    )

    payload = json.loads(result.content)

    assert payload == {
        "question": {
            "header": "",
            "question": "Please choose a city",
            "input_type": "select",
            "options": [
                {"label": "Beijing", "description": "Capital"},
            ],
            "multiple": False,
        }
    }

def test_ask_user_schema_describes_input_type_contract():
    registry = ToolRegistry()
    registry.register_by_metadata("ask_user")

    schema = registry.get_schema()[0]["function"]
    properties = schema["parameters"]["properties"]
    input_type = properties["input_type"]
    options = properties["options"]

    assert "must set input_type explicitly" in schema["description"]
    assert "Use 'text' for free-form typed input" in input_type["description"]
    assert "For input_type='text'" in options["description"]
    assert schema["parameters"]["required"] == ["question", "input_type", "options"]
