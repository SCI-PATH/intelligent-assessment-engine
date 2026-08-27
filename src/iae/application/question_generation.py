"""Shared question-generation path used by the bank script and teacher API."""

from __future__ import annotations

import random
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from pydantic import ValidationError

from iae.domain.curriculum import get_chapter_names
from iae.domain.models import (
    Chunk,
    DistractorTag,
    MCQPayload,
    MultiBlankPayload,
    OptionDiagnostic,
    Question,
    QuestionOrigin,
    QuestionStatus,
    QuestionType,
    ShortAnswerPayload,
    TrueFalsePayload,
)
from iae.domain.protocols import IEmbedder, ILlmJson, IVectorStore
from iae.domain.skills import get_topic, normalize_chapter_name, topics_for_chapter
from iae.prompts import render

DOK_DESCRIPTORS: dict[int, str] = {
    1: "Recall: identify or state a single fact from the text.",
    2: "Skill / Concept: explain a process or compare two ideas using textbook content.",
    3: "Strategic Thinking: justify, infer, or apply concepts to a short scenario.",
    4: "Extended Thinking: synthesize across paragraphs or design a small investigation.",
}

PROMPT_FOR_TYPE: dict[QuestionType, str] = {
    QuestionType.MCQ: "question_bank_generation/mcq.jinja",
    QuestionType.SHORT_ANSWER: "question_bank_generation/short_answer.jinja",
    QuestionType.MULTI_BLANK: "question_bank_generation/multi_blank.jinja",
    QuestionType.TRUE_FALSE: "question_bank_generation/true_false.jinja",
}

_BLANK_TOKEN_RE = re.compile(r"\[_+\]|_{3,}|\[\s*blank\s*\d+\s*\]|\[\s*\]", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class RateLimitExceeded(RuntimeError):
    """Raised when provider daily quota is exhausted."""


@dataclass
class GenerationStats:
    succeeded: int = 0
    failed: int = 0


def curriculum_chapter_for_topic(topic_chapter_title: str, grade: int) -> str:
    needle = normalize_chapter_name(topic_chapter_title)
    for name in get_chapter_names(grade):
        if normalize_chapter_name(name) == needle:
            return name
    return topic_chapter_title


def stem_text(question: Question) -> str:
    """Comparable stem / statement / paragraph for distinctness checks."""
    payload = question.payload
    if isinstance(payload, MCQPayload):
        return str(payload.question or "").strip()
    if isinstance(payload, ShortAnswerPayload):
        return str(payload.question or "").strip()
    if isinstance(payload, TrueFalsePayload):
        return str(payload.question or "").strip()
    if isinstance(payload, MultiBlankPayload):
        return str(payload.paragraph or "").strip()
    return ""


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def token_jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_distinct_stem(
    candidate: str,
    prior_stems: list[str],
    *,
    jaccard_max: float = 0.85,
) -> bool:
    """True when candidate is not a near-paraphrase of any prior stem."""
    cand = (candidate or "").strip()
    if not cand:
        return False
    for prior in prior_stems:
        if token_jaccard(cand, prior) >= jaccard_max:
            return False
    return True


def _canonicalize_blanks(paragraph: str) -> str:
    return _BLANK_TOKEN_RE.sub("[_____]", paragraph)


def _parse_distractor_tag(raw: object) -> DistractorTag:
    value = str(raw or "").strip().upper()
    try:
        return DistractorTag(value)
    except ValueError:
        return DistractorTag.MISCONCEPTION


def _shuffle_mcq_options(raw: dict) -> dict:
    options = raw.get("options", {})
    correct_letter = str(raw.get("correct_answer", "")).strip().upper()
    if not isinstance(options, dict) or len(options) != 4 or correct_letter not in options:
        raise ValueError("Invalid MCQ payload shape")

    pairs = [(k, str(v).strip()) for k, v in options.items()]
    random.shuffle(pairs)
    letters = ("A", "B", "C", "D")
    old_to_new: dict[str, str] = {}

    new_options: dict[str, str] = {}
    new_correct = "A"
    for idx, (old_key, text) in enumerate(pairs):
        letter = letters[idx]
        old_to_new[str(old_key).strip().upper()] = letter
        new_options[letter] = text
        if old_key == correct_letter:
            new_correct = letter

    # Remap option_diagnostics keys to post-shuffle letters (wrong options only).
    raw_diag = raw.get("option_diagnostics") or {}
    new_diag: dict[str, dict[str, str]] = {}
    if isinstance(raw_diag, dict):
        for old_key, entry in raw_diag.items():
            new_letter = old_to_new.get(str(old_key).strip().upper())
            if not new_letter or new_letter == new_correct:
                continue
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("distractor_label") or "").strip()
            if not label:
                continue
            new_diag[new_letter] = {
                "distractor_tag": _parse_distractor_tag(entry.get("distractor_tag")).value,
                "distractor_label": label,
            }

    return {
        "question": str(raw.get("question", "")).strip(),
        "options": new_options,
        "correct_answer": new_correct,
        "option_diagnostics": new_diag,
    }


def _normalize_short_answer(raw: dict) -> dict:
    keywords = [str(k).strip().lower() for k in raw.get("keywords", []) if str(k).strip()]
    deduped: list[str] = []
    for kw in keywords:
        if kw not in deduped:
            deduped.append(kw)
    if len(deduped) < 3:
        raise ValueError("ShortAnswer requires at least 3 usable keywords")
    return {
        "question": str(raw.get("question", "")).strip(),
        "ideal_answer": str(raw.get("ideal_answer", "")).strip(),
        "keywords": deduped[:6],
    }


def _normalize_multiblank(raw: dict) -> dict:
    answers = [str(a).strip().lower() for a in raw.get("answers", []) if str(a).strip()]
    if not (3 <= len(answers) <= 5):
        raise ValueError("MultiBlank requires 3-5 non-empty answers")

    paragraph = _canonicalize_blanks(str(raw.get("paragraph", "")).strip())
    blanks = _BLANK_TOKEN_RE.findall(paragraph)
    if len(blanks) != len(answers):
        raise ValueError("MultiBlank paragraph blank count must match answers length")

    return {"paragraph": paragraph, "answers": answers}


def _normalize_true_false(raw: dict) -> dict:
    answer = str(raw.get("correct_answer", "")).strip().lower()
    if answer in ("t", "true"):
        canonical = "True"
    elif answer in ("f", "false"):
        canonical = "False"
    else:
        raise ValueError("TrueFalse correct_answer must be True/False")
    tag = _parse_distractor_tag(raw.get("distractor_tag"))
    label = str(raw.get("distractor_label") or "").strip()
    result: dict = {
        "question": str(raw.get("question", "")).strip(),
        "correct_answer": canonical,
    }
    if label:
        result["distractor_tag"] = tag
        result["distractor_label"] = label
    return result


def build_payload(qtype: QuestionType, raw: dict):
    if qtype == QuestionType.MCQ:
        normalized = _shuffle_mcq_options(raw)
        diag_raw = normalized.pop("option_diagnostics", {}) or {}
        diagnostics: dict[str, OptionDiagnostic] = {}
        for letter, entry in diag_raw.items():
            if not isinstance(entry, dict):
                continue
            diagnostics[letter] = OptionDiagnostic(
                distractor_tag=_parse_distractor_tag(entry.get("distractor_tag")),
                distractor_label=str(entry.get("distractor_label") or "").strip(),
            )
        return MCQPayload(**normalized, option_diagnostics=diagnostics)
    if qtype == QuestionType.SHORT_ANSWER:
        return ShortAnswerPayload(**_normalize_short_answer(raw))
    if qtype == QuestionType.MULTI_BLANK:
        return MultiBlankPayload(**_normalize_multiblank(raw))
    return TrueFalsePayload(**_normalize_true_false(raw))


def format_context(chunk_texts: Iterable[str]) -> str:
    return "\n\n---\n\n".join(t.strip() for t in chunk_texts)


def majority_topic(chunks: list[Chunk]) -> tuple[str, str]:
    tagged = [(c.topic_id, c.skill) for c in chunks if c.topic_id]
    if not tagged:
        return "", ""
    topic_id = Counter(pair[0] for pair in tagged).most_common(1)[0][0]
    skill = next(skill for tid, skill in tagged if tid == topic_id)
    return topic_id, skill


def retrieve_chunks(
    *,
    store: IVectorStore,
    embedder: IEmbedder,
    grade: int,
    chapter: str,
    topic_ids: list[str | None],
    top_k: int,
) -> list[Chunk]:
    collected: list[Chunk] = []
    seen: set[str] = set()
    query_bits = [chapter]
    for topic_id in topic_ids:
        if topic_id:
            topic = get_topic(topic_id)
            if topic and topic.skill:
                query_bits.append(topic.skill)
    query_embedding = embedder.embed([" ".join(query_bits)])[0]

    for topic_id in topic_ids:
        hits = store.query(
            query_embedding,
            n_results=top_k,
            grade=grade,
            chapter_name=None if topic_id else chapter,
            topic_id=topic_id,
        )
        if not hits and topic_id:
            hits = store.find(grade=grade, topic_id=topic_id, limit=top_k)
        for chunk in hits:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            collected.append(chunk)
            if len(collected) >= top_k:
                return collected

    if not collected:
        collected = store.find(grade=grade, chapter_name=chapter, limit=top_k)
    return collected[:top_k]


def generate_one(
    *,
    llm: ILlmJson,
    chapter: str,
    sub_concept: str,
    dok: int,
    qtype: QuestionType,
    context: str,
    chunk_ids: list[str],
    grade: int,
    topic_id: str,
    skill: str,
    max_retries: int,
    status: QuestionStatus = QuestionStatus.PENDING,
    origin: QuestionOrigin = QuestionOrigin.AI,
    stop_on_rate_limit: bool = True,
    avoid_stems: list[str] | None = None,
) -> Question | None:
    prompt = render(
        PROMPT_FOR_TYPE[qtype],
        chapter_name=chapter,
        sub_concept=sub_concept,
        dok_level=dok,
        dok_descriptor=DOK_DESCRIPTORS[dok],
        context=context,
        avoid_stems=list(avoid_stems or []),
    )
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            raw = llm.generate_json(prompt, temperature=0.7)
            payload = build_payload(qtype, raw)
            return Question(
                chapter_name=chapter,
                sub_concept=sub_concept,
                dok_level=dok,
                question_type=qtype,
                payload=payload,
                chunk_ids=chunk_ids,
                grade=grade,
                topic_id=topic_id,
                skill=skill,
                status=status,
                origin=origin,
            )
        except (ValidationError, ValueError, KeyError) as exc:
            last_error = exc
            time.sleep(0.5 * (attempt + 1))
        except Exception as exc:
            last_error = exc
            msg = str(exc).lower()
            if stop_on_rate_limit and ("rate limit" in msg or "429" in msg or "tpd" in msg):
                raise RateLimitExceeded(str(exc)) from exc
            time.sleep(1.0 * (attempt + 1))
    print(f"    ! {chapter} / DOK{dok} / {qtype.value} failed: {last_error}")
    return None


def generate_distinct_for_combo(
    *,
    llm: ILlmJson,
    chapter: str,
    sub_concept: str,
    dok: int,
    qtype: QuestionType,
    context: str,
    chunk_ids: list[str],
    grade: int,
    topic_id: str,
    skill: str,
    max_retries: int,
    target_count: int = 3,
    jaccard_max: float = 0.85,
    status: QuestionStatus = QuestionStatus.PENDING,
    origin: QuestionOrigin = QuestionOrigin.AI,
    stop_on_rate_limit: bool = True,
    max_attempts: int | None = None,
) -> list[Question]:
    """Aim for ``target_count`` conceptually distinct items; keep 1+ if clones only.

    One high-quality distinct question is preferred over three paraphrases.
    """
    target = max(1, int(target_count))
    attempts_budget = max_attempts if max_attempts is not None else target + 2
    produced: list[Question] = []
    stems: list[str] = []
    for _ in range(attempts_budget):
        if len(produced) >= target:
            break
        question = generate_one(
            llm=llm,
            chapter=chapter,
            sub_concept=sub_concept,
            dok=dok,
            qtype=qtype,
            context=context,
            chunk_ids=chunk_ids,
            grade=grade,
            topic_id=topic_id,
            skill=skill,
            max_retries=max_retries,
            status=status,
            origin=origin,
            stop_on_rate_limit=stop_on_rate_limit,
            avoid_stems=stems,
        )
        if question is None:
            continue
        text = stem_text(question)
        if stems and not is_distinct_stem(text, stems, jaccard_max=jaccard_max):
            print(
                f"    skip clone dok={dok} type={qtype.value} "
                f"(jaccard vs prior >= {jaccard_max})"
            )
            continue
        produced.append(question)
        if text:
            stems.append(text)
    return produced


def generate_for_topic(
    *,
    llm: ILlmJson,
    store: IVectorStore,
    embedder: IEmbedder,
    topic_id: str,
    skill: str | None = None,
    dok_level: int = 2,
    question_type: QuestionType = QuestionType.MCQ,
    count: int = 1,
    top_k: int = 4,
    max_retries: int = 2,
    status: QuestionStatus = QuestionStatus.PENDING,
    origin: QuestionOrigin = QuestionOrigin.AI,
    jaccard_max: float = 0.85,
) -> list[Question]:
    topic = get_topic(topic_id)
    if topic is None:
        raise KeyError(f"Unknown Topic ID: {topic_id}")
    chapter = curriculum_chapter_for_topic(topic.chapter_title, topic.grade)
    resolved_skill = (skill or topic.skill).strip()
    chunks = retrieve_chunks(
        store=store,
        embedder=embedder,
        grade=topic.grade,
        chapter=chapter,
        topic_ids=[topic.topic_id],
        top_k=top_k,
    )
    if not chunks:
        raise LookupError(
            f"No Chroma chunks for topic {topic_id}. Ingest the grade {topic.grade} PDF first."
        )
    context = format_context(c.text for c in chunks)
    chunk_ids = [c.id for c in chunks]
    return generate_distinct_for_combo(
        llm=llm,
        chapter=chapter,
        sub_concept=resolved_skill or topic.skill or "ChapterWide",
        dok=dok_level,
        qtype=question_type,
        context=context,
        chunk_ids=chunk_ids,
        grade=topic.grade,
        topic_id=topic.topic_id,
        skill=resolved_skill,
        max_retries=max_retries,
        target_count=max(1, count),
        jaccard_max=jaccard_max,
        status=status,
        origin=origin,
    )


def topics_for_bank_chapter(chapter: str, grade: int, topic_id: str | None) -> list[str | None]:
    if topic_id:
        return [topic_id]
    ids = [t.topic_id for t in topics_for_chapter(chapter, grade)]
    return ids or [None]
