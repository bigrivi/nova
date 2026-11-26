"""Nova compatibility exports for portable threat screening."""

from novakit.prompt.threat_patterns import THREAT_PATTERNS, has_threats, scan_text

__all__ = ["THREAT_PATTERNS", "has_threats", "scan_text"]
