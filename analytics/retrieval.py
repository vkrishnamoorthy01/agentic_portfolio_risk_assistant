"""Embedding retrieval over a versioned risk policy.

  document -> passages -> embeddings -> in-memory vectors -> clause ranking

Two policy versions are kept, so earlier results stay reproducible:

- v1 (policy/risk_policy_v1.md): the original five short sections. Each
  "## " section is one passage; all fit the model's input limit.
- v2.1 (policy/risk_policy_v2.md, the default): 32 clauses RP01-RP32. Four
  whole clauses are longer than the embedding model reads (256 tokens), so
  embedding them whole would silently drop their ends (for RP25 Escalation,
  the record-keeping paragraph). Each paragraph is therefore its own
  passage, prefixed with its clause number, title and policy version so it
  keeps its parent context.

Ranking is by clause: each clause scores as its best-matching passage, and
retrieve() returns the top_k distinct clauses with their full text, so a
limit is never separated from the exceptions and escalation rules written
next to it. Scores are cosine similarities used for ranking only; they are
not probabilities that a clause answers the question.

A passage longer than the model's limit raises an error when the index is
built instead of being truncated. policy/index_v2.1.json records every
passage's token count and the corpus hash (scripts/build_policy_index.py),
so tests can check this without loading the model.

sentence-transformers (and PyTorch) is imported only when the model is
first needed. In the Docker image the model is downloaded at build time and
loaded from the local cache, with no network call at runtime.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

POLICY_DIR = Path(__file__).parent.parent / "policy"
POLICY_FILES = {"v1": POLICY_DIR / "risk_policy_v1.md", "v2.1": POLICY_DIR / "risk_policy_v2.md"}
DEFAULT_POLICY_VERSION = "v2.1"
POLICY_VERSION = os.environ.get("POLICY_VERSION", DEFAULT_POLICY_VERSION)
# v1 keeps its original one-passage-per-section chunking so its results stay reproducible.
DEFAULT_CHUNKING = {"v1": "clause", "v2.1": "paragraph"}
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
MAX_QUERY_CHARS = 500
# The limit and escalation clauses an overall risk question needs. Search alone often misses them:
# broad questions match the worked examples (RP29, RP30) instead (eval/VALIDATION_REPORT.md).
CORE_CLAUSES = {"v2.1": ("RP13", "RP15", "RP17", "RP19", "RP25"), "v1": ()}

_V2_HEADING = re.compile(r"^## (RP\d{2}) (.+)$")
_V1_HEADING = re.compile(r"^## (\d+)\. (.+)$")

_model: SentenceTransformer | None = None
_indexes: dict[tuple[str, str], tuple[list[Passage], np.ndarray]] = {}


class InvalidQueryError(ValueError):
    """A retrieval request is empty, too long, or asks for an impossible top_k."""


class PassageTooLongError(ValueError):
    """A passage exceeds the embedding model's input limit and would be truncated."""


@dataclass(frozen=True)
class Clause:
    clause_id: str  # "RP13" (v2.1) or "S1" (v1)
    title: str
    policy_version: str
    text: str  # the full clause, heading included


@dataclass(frozen=True)
class Passage:
    passage_id: str  # "RP13.p2"
    clause_id: str
    title: str
    policy_version: str
    body: str  # the paragraph (or whole v1 section) without context
    embed_text: str  # what is embedded: context header + body


def corpus_sha256(version: str = POLICY_VERSION) -> str:
    """SHA-256 of the policy text with line endings normalized to LF (stable across checkouts)."""
    text = POLICY_FILES[version].read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(text).hexdigest()


def parse_clauses(version: str = POLICY_VERSION) -> list[Clause]:
    """Split a policy file into its numbered clauses."""
    if version not in POLICY_FILES:
        raise ValueError(f"Unknown policy version {version!r}; use one of {sorted(POLICY_FILES)}.")
    text = POLICY_FILES[version].read_text(encoding="utf-8").replace("\r\n", "\n")
    heading = _V2_HEADING if version == "v2.1" else _V1_HEADING
    clauses = []
    for section in re.split(r"\n(?=## )", text):
        section = section.strip()
        match = heading.match(section.splitlines()[0]) if section.startswith("## ") else None
        if not match:
            continue
        number, title = match.groups()
        clause_id = number if version == "v2.1" else f"S{number}"
        clauses.append(Clause(clause_id, title.strip(), version, section))
    return clauses


def build_passages(version: str = POLICY_VERSION, chunking: str | None = None) -> list[Passage]:
    """Passages to embed.

    chunking="paragraph" (default): one passage per paragraph, prefixed with
    "<clause number> <title> (policy <version>)". chunking="clause": one passage
    per whole clause, as the original code did; kept for comparison only, since
    long v2.1 clauses exceed the model's input limit. Default: DEFAULT_CHUNKING.
    """
    chunking = chunking or DEFAULT_CHUNKING[version]
    passages = []
    for clause in parse_clauses(version):
        if chunking == "clause":
            parts = [clause.text]
        else:
            parts = [p.strip() for p in clause.text.split("\n\n")[1:] if p.strip()] or [clause.text]
        for i, body in enumerate(parts, start=1):
            header = f"{clause.clause_id} {clause.title} (policy {version})"
            embed_text = body if chunking == "clause" else f"{header}. {body}"
            passages.append(Passage(f"{clause.clause_id}.p{i}", clause.clause_id, clause.title, version, body, embed_text))
    return passages


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def token_lengths(passages: list[Passage]) -> list[int]:
    """Token counts in the embedding model's own tokenizer, special tokens included."""
    tokenizer = _get_model().tokenizer
    return [len(tokenizer(p.embed_text)["input_ids"]) for p in passages]


def _get_index(version: str, chunking: str | None = None, allow_truncation: bool = False) -> tuple[list[Passage], np.ndarray]:
    chunking = chunking or DEFAULT_CHUNKING[version]
    key = (version, chunking)
    if key not in _indexes:
        passages = build_passages(version, chunking)
        model = _get_model()
        too_long = [(p.passage_id, n) for p, n in zip(passages, token_lengths(passages)) if n > model.max_seq_length]
        if too_long and not allow_truncation:
            raise PassageTooLongError(
                f"{len(too_long)} passage(s) exceed the {model.max_seq_length}-token limit and would be "
                f"silently truncated: {too_long}"
            )
        embeddings = model.encode([p.embed_text for p in passages], normalize_embeddings=True, show_progress_bar=False)
        _indexes[key] = (passages, embeddings)
    return _indexes[key]


def policy_section_count(version: str = POLICY_VERSION) -> int:
    """Number of clauses, without loading the embedding model."""
    return len(parse_clauses(version))


def warm_up() -> None:
    """Load the model and embed the default policy now, so the first request isn't slow."""
    _get_index(POLICY_VERSION)


def rank_clauses(
    query: str,
    version: str = POLICY_VERSION,
    chunking: str | None = None,
    extra_passages: list[Passage] | None = None,
    allow_truncation: bool = False,
) -> list[dict[str, Any]]:
    """Every clause ranked by its best passage's similarity to the query (evaluation and retrieve()).

    extra_passages adds passages to an isolated copy of the index (used to test
    injected content); the stored index is never modified.
    """
    passages, embeddings = _get_index(version, chunking, allow_truncation)
    model = _get_model()
    if extra_passages:
        extra = model.encode([p.embed_text for p in extra_passages], normalize_embeddings=True, show_progress_bar=False)
        passages, embeddings = passages + list(extra_passages), np.vstack([embeddings, extra])
    query_embedding = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]
    scores = embeddings @ query_embedding

    best: dict[str, tuple[float, Passage]] = {}
    for passage, score in zip(passages, scores):
        if passage.clause_id not in best or score > best[passage.clause_id][0]:
            best[passage.clause_id] = (float(score), passage)
    ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
    return [
        {"clause_id": p.clause_id, "title": p.title, "policy_version": p.policy_version,
         "passage_id": p.passage_id, "score": round(score, 4), "matched_passage": p.body}
        for score, p in ranked
    ]


def retrieve(query: str, top_k: int = 2, version: str = POLICY_VERSION, include_core: bool = False) -> list[dict[str, Any]]:
    """Return the top_k policy clauses most similar to the query, with their full text.

    include_core=True puts the core limit and escalation clauses (CORE_CLAUSES) first,
    whatever the query, followed by the top_k search results that are not core clauses.
    Each result's "included" says which way it got there ("core" or "search").

    Raises:
        InvalidQueryError: for a blank or overlong query, or top_k outside
            1..number of clauses in the policy.
    """
    if not query or not query.strip():
        raise InvalidQueryError("query must not be empty.")
    if len(query) > MAX_QUERY_CHARS:
        raise InvalidQueryError(f"query is {len(query)} characters; the limit is {MAX_QUERY_CHARS}.")
    count = policy_section_count(version)
    if not 1 <= top_k <= count:
        raise InvalidQueryError(f"top_k must be between 1 and {count}, got {top_k}.")

    clauses = {c.clause_id: c for c in parse_clauses(version)}
    ranked = rank_clauses(query, version)
    core = CORE_CLAUSES.get(version, ()) if include_core else ()
    by_id = {hit["clause_id"]: hit for hit in ranked}
    picked = [(by_id[c], "core") for c in core if c in by_id]
    picked += [(hit, "search") for hit in [h for h in ranked if h["clause_id"] not in core][:top_k]]
    results = []
    for hit, how in picked:
        clause = clauses[hit["clause_id"]]
        results.append({
            "section": f"{clause.clause_id} {clause.title}",
            "clause_id": clause.clause_id,
            "policy_version": version,
            "text": clause.text,
            "matched_passage": hit["matched_passage"],
            "score": hit["score"],
            "included": how,
        })
    return results
