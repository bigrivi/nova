"""
Tests for nova/llm/tokenizer.py - type-aware token estimation.
"""

from unittest.mock import patch

from nova.llm.tokenizer import (
    CHARS_PER_TOKEN_TEXT,
    CHARS_PER_TOKEN_TOOL,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens_by_type,
    resolve_context_limit,
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
        # chars=18, /4 = 4.5 -> 4
        assert result > 0
        assert isinstance(result, int)

    def test_string_content_tool(self):
        """Tool result with string content (uses chars/2)."""
        msg = MockMessage("tool", "A" * 100)
        result = estimate_message_tokens(msg, model="unknown")
        # 100/2=50
        assert result == 50

    def test_list_content_with_text(self):
        """Message with list content containing text blocks."""
        msg = MockMessage(
            "assistant",
            [{"type": "text", "text": "Hello"}, {"type": "text", "text": "World"}],
        )
        result = estimate_message_tokens(msg, model="gpt-4")
        # "Hello"=5, "World"=5, total=10, /4=2 (int)
        assert result == 2

    def test_list_content_with_image(self):
        """Message with image block (fixed 8000 char estimate)."""
        msg = MockMessage(
            "user",
            [
                {"type": "image", "image_url": "..."},
                {"type": "text", "text": "What's this?"},
            ],
        )
        result = estimate_message_tokens(msg, model="gpt-4")
        # text=12/4=3, image=8000//4=2000, total=2003
        assert result >= 2000

    def test_list_content_with_thinking(self):
        """Assistant message with thinking block."""
        msg = MockMessage(
            "assistant",
            [
                {"type": "thinking", "thinking": "Let me think..."},
                {"type": "text", "text": "Hello"},
            ],
        )
        result = estimate_message_tokens(msg, model="gpt-4")
        # thinking=str->15/4=3, text=5/4=1, total=4
        assert result == 4

    def test_with_tool_calls(self):
        """Message with tool calls."""
        msg = MockMessage(
            "assistant",
            [{"type": "toolCall", "name": "read", "arguments": {"file": "test.py"}}],
        )
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
            MockMessage("user", "How are you?"),
        ]
        result = estimate_messages_tokens(messages, model="gpt-4")
        assert result > 0
        assert isinstance(result, int)

    def test_mixed_roles(self):
        """Messages with different roles."""
        messages = [
            MockMessage("user", "A" * 100),
            MockMessage("tool", "B" * 200),  # Tool result uses chars/2
            MockMessage("assitant", "C" * 50),
        ]
        result = estimate_messages_tokens(messages, model="gpt-4")
        # The gpt-4 path uses tiktoken: 13 + 50 + 12. The removed 1.2 pad was
        # applied per message, not to the sum, which is where 15 + 60 + 14 = 89
        # came from.
        assert result == 75


class TestResolveContextLimit:
    """The planned window is the one the provider states, undivided."""

    def test_known_model(self):
        result = resolve_context_limit("gpt-4o", provider="openai")
        assert result == 128000

    def test_gpt4(self):
        """GPT-4 has 8192 context window."""
        result = resolve_context_limit("gpt-4", provider="openai")
        assert result == 8192

    def test_gemma(self):
        result = resolve_context_limit("gemma4:26b", provider="ollama")
        assert result == 32000

    def test_unknown_model(self):
        """Unknown model falls back to the default window, still undivided."""
        result = resolve_context_limit("unknown-model", provider="openai")
        assert result == 128000


class TestNoEstimatePadding:
    """Estimates are reported as measured, with no global multiplier.

    A blanket 1.2 was applied to every estimate. Measured against a real
    tokenizer the character heuristic already over-counts prose by 6-45% and only
    under-counts code, so the pad inflated the common case while silently scaling
    every budget compared against an estimate - including the recent-portion
    budget, which therefore retained 20% more content than it was set to. A
    request that still overshoots is handled by compacting and retrying, not by
    padding the number.
    """

    def test_there_is_no_margin_constant(self):
        import nova.llm.tokenizer as tokenizer

        assert not hasattr(tokenizer, "SAFETY_MARGIN")

    def test_prose_is_the_bare_character_ratio(self):
        text = "the assistant completed the recommendations for the plaza"
        result = estimate_message_tokens(MockMessage("user", text), model="unknown")
        assert result == len(text) // 4

    def test_tool_results_use_their_own_ratio(self):
        """Tool output is denser, so it gets 2 chars per token, not 4."""
        result = estimate_message_tokens(
            MockMessage("tool", "A" * 100), model="unknown"
        )
        assert result == 50


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
        from unittest.mock import MagicMock

        mock_settings = MagicMock()
        mock_settings.providers = {}

        for provider_name, provider_data in providers_dict.items():
            mock_provider = MagicMock()
            mock_provider.models = provider_data.get("models", {})
            mock_settings.providers[provider_name] = mock_provider

        return mock_settings

    def test_provider_model_joint_lookup(self):
        """Joint provider+model lookup returns correct limit."""
        mock = self._mock_settings(
            {
                "ollama": {"models": {"gemma4:26b": {"limit": {"context": 32000}}}},
                "openai": {"models": {"gpt-4o": {"limit": {"context": 128000}}}},
            }
        )

        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings

            get_settings.cache_clear()
            result = resolve_context_limit("gemma4:26b", provider="ollama")
            assert result == 32000

    def test_provider_model_limit_context_priority(self):
        """limit.context takes priority over context_window."""
        mock = self._mock_settings(
            {
                "openai": {
                    "models": {
                        "gpt-4o": {
                            "limit": {"context": 200000},
                            "context_window": 128000,
                        }
                    }
                }
            }
        )

        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings

            get_settings.cache_clear()
            result = resolve_context_limit("gpt-4o", provider="openai")
            assert result == 200000

    def test_provider_model_context_window_fallback(self):
        """Falls back to context_window when limit.context missing."""
        mock = self._mock_settings(
            {"anthropic": {"models": {"claude-3-5-sonnet": {"context_window": 200000}}}}
        )

        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings

            get_settings.cache_clear()
            result = resolve_context_limit("claude-3-5-sonnet", provider="anthropic")
            assert result == 200000

    def test_unknown_provider_falls_back_to_hardcoded(self):
        """Unknown provider falls back to hardcoded defaults."""
        mock = self._mock_settings({})

        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings

            get_settings.cache_clear()
            result = resolve_context_limit("gpt-4o", provider="unknown-provider")
            assert result == 128000

    def test_unknown_model_falls_back_to_hardcoded(self):
        """Unknown model in known provider falls back to hardcoded defaults."""
        mock = self._mock_settings({"openai": {"models": {}}})

        with patch("nova.settings.get_settings", return_value=mock):
            from nova.settings import get_settings

            get_settings.cache_clear()
            result = resolve_context_limit("unknown-model", provider="openai")
            assert result == 128000
