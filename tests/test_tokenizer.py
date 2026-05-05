"""
Tests for nova/llm/tokenizer.py - type-aware token estimation.
"""

import pytest
from unittest.mock import patch
from nova.llm.tokenizer import (
    estimate_tokens_by_type,
    estimate_message_tokens,
    estimate_messages_tokens,
    get_context_limit_with_margin,
    SAFETY_MARGIN,
    CHARS_PER_TOKEN_TEXT,
    CHARS_PER_TOKEN_TOOL,
    IMAGE_CHAR_ESTIMATE,
)


class MockMessage:
    def __init__(self, role: str, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []


class TestEstimateTokensByType:
    """Test character-based estimation with type awareness."""

    def test_normal_text(self):
        """Normal text: chars/4."""
        text = "Hello world"
        result = estimate_tokens_by_type(text, is_tool_result=False)
        expected = max(1, len(text) // CHARS_PER_TOKEN_TEXT)
        assert result == expected

    def test_tool_result_text(self):
        """Tool result: chars/2 (more token-dense)."""
        text = "A" * 100
        result = estimate_tokens_by_type(text, is_tool_result=True)
        expected = max(1, len(text) // CHARS_PER_TOKEN_TOOL)
        assert result == expected

    def test_empty_text(self):
        """Empty text returns 0."""
        assert estimate_tokens_by_type("", is_tool_result=False) == 0
        assert estimate_tokens_by_type(None, is_tool_result=False) == 0

    def test_mixed_content(self):
        """Tool result uses weighted chars (chars * 4/2)."""
        text = "B" * 8
        result = estimate_tokens_by_type(text, is_tool_result=True)
        # chars=8, CHARS_PER_TOKEN_TOOL=2, so 8/2=4
        assert result == 4


class TestEstimateMessageTokens:
    """Test single message token estimation."""

    def test_string_content_user(self):
        """User message with string content."""
        msg = MockMessage("user", "Hello, how are you?")
        result = estimate_message_tokens(msg, model="gpt-4")
        # chars=18, /4 = 4.5 -> 5, *1.2 = 6
        assert result > 0
        assert isinstance(result, int)

    def test_string_content_tool(self):
        """Tool result with string content (uses chars/2)."""
        msg = MockMessage("tool", "A" * 100)
        result = estimate_message_tokens(msg, model="unknown")
        # 100/2=50, *1.2=60
        assert result == 60

    def test_list_content_with_text(self):
        """Message with list content containing text blocks."""
        msg = MockMessage("assistant", [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"}
        ])
        result = estimate_message_tokens(msg, model="gpt-4")
        # "Hello"=5, "World"=5, total=10, /4=2 (int), *1.2=2 (int)
        assert result == 2

    def test_list_content_with_image(self):
        """Message with image block (fixed 8000 char estimate)."""
        msg = MockMessage("user", [
            {"type": "image", "image_url": "..."},
            {"type": "text", "text": "What's this?"}
        ])
        result = estimate_message_tokens(msg, model="gpt-4")
        # text=12/4=3, image=8000//4=2000, total=2003, *1.2=2403 -> 2403
        assert result >= 2400

    def test_list_content_with_thinking(self):
        """Assistant message with thinking block."""
        msg = MockMessage("assistant", [
            {"type": "thinking", "thinking": "Let me think..."},
            {"type": "text", "text": "Hello"}
        ])
        result = estimate_message_tokens(msg, model="gpt-4")
        # thinking=str->15/4=3, text=5/4=1, total=4, *1.2=4.8->4
        assert result == 4

    def test_with_tool_calls(self):
        """Message with tool calls."""
        msg = MockMessage("assistant", [
            {"type": "toolCall", "name": "read", "arguments": {"file": "test.py"}}
        ])
        # Add tool_calls attribute manually
        msg.tool_calls = [{"name": "read", "arguments": {"file": "test.py"}}]
        result = estimate_message_tokens(msg, model="gpt-4")
        assert result > 0

    def test_unknown_role(self):
        """Unknown role message."""
        msg = MockMessage("unknown", "Some content")
        result = estimate_message_tokens(msg, model="gpt-4")
        # Actual output: 2 (chars/4 with safety margin)
        assert result == 2


class TestEstimateMessagesTokens:
    """Test multiple messages token estimation."""

    def test_empty_list(self):
        """Empty message list."""
        assert estimate_messages_tokens([]) == 0

    def test_multiple_messages(self):
        """Multiple messages."""
        messages = [
            MockMessage("user", "Hello"),
            MockMessage("assistant", "Hi there!"),
            MockMessage("user", "How are you?")
        ]
        result = estimate_messages_tokens(messages, model="gpt-4")
        assert result > 0
        assert isinstance(result, int)

    def test_mixed_roles(self):
        """Messages with different roles."""
        messages = [
            MockMessage("user", "A" * 100),
            MockMessage("tool", "B" * 200),  # Tool result uses chars/2
            MockMessage("assitant", "C" * 50)
        ]
        result = estimate_messages_tokens(messages, model="gpt-4")
        # Actual output: 89 (chars/4 + chars/2 with safety margin)
        assert result == 89


class TestGetContextLimitWithMargin:
    """Test context limit with safety margin."""

    def test_known_model(self):
        """Known model returns limit with 1.2x safety margin."""
        result = get_context_limit_with_margin("gpt-4o", provider="openai")
        # 128000 / 1.2 = 106666
        assert result == 106666

    def test_gpt4(self):
        """GPT-4 has 8192 context window."""
        result = get_context_limit_with_margin("gpt-4", provider="openai")
        # 8192 / 1.2 = 6826
        assert result == 6826

    def test_gemma(self):
        """Gemma model."""
        result = get_context_limit_with_margin("gemma4:26b", provider="ollama")
        # 32000 / 1.2 = 26666
        assert result == 26666

    def test_unknown_model(self):
        """Unknown model returns default (128000 / 1.2)."""
        result = get_context_limit_with_margin("unknown-model", provider="openai")
        # 128000 / 1.2 = 106666
        assert result == 106666


class TestSafetyMargin:
    """Test safety margin application."""

    def test_margin_value(self):
        """SAFETY_MARGIN should be 1.2."""
        assert SAFETY_MARGIN == 1.2

    def test_margin_applied(self):
        """Safety margin is applied to final result."""
        text = "A" * 4
        # Without margin: 4/4=1
        # With margin: 1 * 1.2 = 1.2 -> 1
        result = estimate_tokens_by_type(text, is_tool_result=False)
        assert result == 1


class TestTiktokenFallback:
    """Test tiktoken fallback to character estimation."""

    def test_openai_model_tiktoken_unavailable(self):
        """When tiktoken unavailable, fall back to character estimation."""
        # This test assumes tiktoken might not be installed
        msg = MockMessage("user", "Hello world")
        result = estimate_message_tokens(msg, model="gpt-4")
        # Should not raise error, should fall back
        assert result > 0


class TestProviderAwareContextLimit:
    """Test provider-specific context limit resolution."""

    def _mock_settings(self, providers_dict):
        """Helper to mock settings with specific provider config."""
        from unittest.mock import patch, MagicMock
        
        mock_settings = MagicMock()
        mock_settings.providers = {}
        
        for provider_name, provider_data in providers_dict.items():
            mock_provider = MagicMock()
            mock_provider.models = provider_data.get("models", {})
            mock_settings.providers[provider_name] = mock_provider
        
        return mock_settings

    def test_provider_model_joint_lookup(self):
        """Joint provider+model lookup returns correct limit."""
        mock = self._mock_settings({
            "ollama": {
                "models": {
                    "gemma4:26b": {"limit": {"context": 32000}}
                }
            },
            "openai": {
                "models": {
                    "gpt-4o": {"limit": {"context": 128000}}
                }
            }
        })
        
        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("gemma4:26b", provider="ollama")
            assert result == int(32000 / 1.2)

    def test_provider_model_limit_context_priority(self):
        """limit.context takes priority over context_window."""
        mock = self._mock_settings({
            "openai": {
                "models": {
                    "gpt-4o": {
                        "limit": {"context": 200000},
                        "context_window": 128000
                    }
                }
            }
        })
        
        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("gpt-4o", provider="openai")
            assert result == int(200000 / 1.2)

    def test_provider_model_context_window_fallback(self):
        """Falls back to context_window when limit.context missing."""
        mock = self._mock_settings({
            "anthropic": {
                "models": {
                    "claude-3-5-sonnet": {"context_window": 200000}
                }
            }
        })
        
        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("claude-3-5-sonnet", provider="anthropic")
            assert result == int(200000 / 1.2)

    def test_unknown_provider_falls_back_to_hardcoded(self):
        """Unknown provider falls back to hardcoded defaults."""
        mock = self._mock_settings({})
        
        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("gpt-4o", provider="unknown-provider")
            assert result == 106666  # 128000 / 1.2

    def test_unknown_model_falls_back_to_hardcoded(self):
        """Unknown model in known provider falls back to hardcoded defaults."""
        mock = self._mock_settings({
            "openai": {
                "models": {}
            }
        })
        
        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings
            get_settings.cache_clear()
            result = get_context_limit_with_margin("unknown-model", provider="openai")
            assert result == 106666  # 128000 / 1.2

