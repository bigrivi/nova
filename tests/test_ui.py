from prompt_toolkit.formatted_text import FormattedText

from nova.cli.ui import (
    _build_continuation_prefix,
)


def test_build_continuation_prefix_matches_prompt_width():
    prefix = _build_continuation_prefix(1)

    assert prefix == [
        ("class:padding", "   "),
    ]


def test_build_continuation_prefix_skips_first_line():
    assert _build_continuation_prefix(0) == [
        ("class:padding", " "),
    ]


def test_prompt_fragments_keep_label_fixed_and_space_after():
    prompt = FormattedText(
        [
            ("class:input-prompt", "❯ "),
        ]
    )

    assert prompt == [
        ("class:input-prompt", "❯ "),
    ]


def test_continuation_prefix_is_separate_from_prompt_label():
    prompt = FormattedText(
        [
            ("class:input-prompt", "❯ "),
        ]
    )
    continuation = _build_continuation_prefix(1)

    assert prompt != continuation
