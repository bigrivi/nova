"""Nova's User-Agent identity for providers supplied by novakit."""

from novakit.llm.user_agent import default_user_agent as _default_user_agent

from nova.version import __version__


def default_user_agent() -> str:
    """Return the Nova-branded provider User-Agent."""
    return _default_user_agent(product="nova", version=__version__)
