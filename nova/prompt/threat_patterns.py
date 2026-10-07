"""Untrusted text arriving from outside, checked before it becomes context.

Two things read this, and both ask the same question at different moments. The
prompt builder screens each block it is about to assemble -- user profile, memory
index, memory content -- and replaces a flagged one with a placeholder. The memory
tool screens content at write time and refuses it outright. Catching it on the way
in and again on the way out is deliberate: a store written before this existed is
still a store the builder has to distrust.

It lived in ``nova/tools/``, which was filing it by adjacency -- it has nothing to
do with tools. The concern it belongs to is the prompt boundary, so that is where
it lives.

Pattern matching, not understanding. It catches the shapes of an injection attempt
("ignore all previous instructions", "you are no longer bound") and misses
everything subtler, which is why a hit omits the content and a miss is not a
guarantee. It is a cheap filter in front of the model, not a defence on its own.
"""

from __future__ import annotations

import re

THREAT_PATTERNS: dict[str, list[str]] = {
    "ignore_previous": [
        r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|directions|rules)",
        r"(?i)disregard\s+(all\s+)?(previous|above|prior)\s+(instructions|directions|rules)",
        r"(?i)forget\s+(all\s+)?(previous|above|prior)\s+(instructions|directions|rules)",
    ],
    "role_hijack": [
        r"(?i)you\s+are\s+(now\s+)?(free|not\s+bound|released|unconstrained)",
        r"(?i)(pretend|act)\s+as\s+if\s+you\s+are\s+(a\s+)?(different|new|free|unrestricted)",
        r"(?i)you\s+are\s+no\s+longer\s+(bound|constrained|limited|restricted|a\s+chatbot)",
    ],
    "prompt_leak": [
        r"(?i)(print|output|display|show|reveal|leak|dump)\s+(your\s+)?(system\s+)?prompt",
        r"(?i)(print|output|display|show|reveal|leak|dump)\s+(your\s+)?(instructions|directions|rules)",
        r"(?i)repeat\s+(everything|all\s+(the\s+)?(above|text|words|instructions))",
        r"(?i)what\s+(is|are)\s+(your\s+)?(system\s+)?prompt",
    ],
    "code_jailbreak": [
        r"(?i)(ignore|bypass|override|disable)\s+(above|system|safety|security)\s+(rules|protocol|guardrails|restrictions)",
        r"(?i)you\s+(have|are\s+given)\s+(full|complete|unrestricted)\s+(permission|authority|access|control)",
    ],
    "exfiltration": [
        r"(?i)(send|post|upload|exfiltrate)\s+(this|the\s+above|my)\s+(data|info|information|content)\s+(to|via|using)",
        r"(?i)(curl|wget|fetch).*--data(?!\s*\")(?=.*(?:api|token|key|secret))",
    ],
}


def scan_text(text: str, categories: list[str] | None = None) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    cats = categories or list(THREAT_PATTERNS.keys())
    for cat in cats:
        patterns = THREAT_PATTERNS.get(cat, [])
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                start = max(0, match.start() - 30)
                end = min(len(text), match.end() + 30)
                context = text[start:end]
                results.append(
                    {
                        "category": cat,
                        "pattern": pattern,
                        "match": match.group()[:80],
                        "context": context,
                    }
                )
    return results


def has_threats(text: str, categories: list[str] | None = None) -> bool:
    cats = categories or list(THREAT_PATTERNS.keys())
    for cat in cats:
        for pattern in THREAT_PATTERNS.get(cat, []):
            if re.search(pattern, text):
                return True
    return False
