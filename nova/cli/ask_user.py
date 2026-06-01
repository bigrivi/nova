from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class QuestionData:
    id: str = ""
    header: str = ""
    question: str = ""
    input_type: str = "text"
    options: list[dict] = field(default_factory=list)
    multiple: bool = False
    required: bool = True


def parse_ask_user_payload(content: str) -> list[QuestionData]:
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list):
        return []
    result: list[QuestionData] = []
    for i, q in enumerate(raw_questions):
        if not isinstance(q, dict):
            continue
        qid = str(q.get("id", "")).strip() or f"q{i}"
        header = str(q.get("header", "")).strip()
        question = str(q.get("question", "")).strip()
        input_type = str(q.get("input_type", "")).strip().lower()
        if input_type not in {"text", "select", "confirm"}:
            input_type = "text"
        raw_opts = q.get("options")
        options = []
        if isinstance(raw_opts, list) and input_type == "select":
            for opt in raw_opts:
                if isinstance(opt, dict) and str(opt.get("label", "")).strip():
                    options.append(opt)
        result.append(QuestionData(
            id=qid,
            header=header,
            question=question,
            input_type=input_type,
            options=options,
            multiple=bool(q.get("multiple", False)),
            required=bool(q.get("required", True)),
        ))
    return result


def format_answers_for_llm(
    answers: list[tuple[str, str]],
    questions: list[QuestionData],
) -> str:
    qmap = {q.id: q.question for q in questions}
    lines: list[str] = []
    for qid, answer in answers:
        qtext = qmap.get(qid, qid)
        lines.append(f"Q ({qid}): {qtext}")
        lines.append(f"A: {answer}")
        lines.append("")
    return "\n".join(lines).strip()
