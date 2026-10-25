"""Write policy/index_<version>.json: every passage with its token count, plus the corpus hash.

    python scripts/build_policy_index.py            # both versions

Run after editing a policy file. The tests compare this manifest with the
policy file (offline, no model), so a policy change without a rebuilt
manifest, or a passage too long for the embedding model, fails CI.
Needs sentence-transformers (for the model's tokenizer).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analytics"))

import retrieval  # noqa: E402

for version in retrieval.POLICY_FILES:
    passages = retrieval.build_passages(version)
    lengths = retrieval.token_lengths(passages)
    limit = retrieval._get_model().max_seq_length
    manifest = {
        "policy_version": version,
        "policy_file": retrieval.POLICY_FILES[version].name,
        "corpus_sha256": retrieval.corpus_sha256(version),
        "embedding_model": retrieval.EMBEDDING_MODEL_NAME,
        "max_seq_length": limit,
        "chunking": retrieval.DEFAULT_CHUNKING[version],
        "clause_count": retrieval.policy_section_count(version),
        "passages": [
            {"passage_id": p.passage_id, "clause_id": p.clause_id, "title": p.title, "tokens": n}
            for p, n in zip(passages, lengths)
        ],
    }
    out = retrieval.POLICY_DIR / f"index_{version}.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"{out.name}: {len(passages)} passages, max {max(lengths)} of {limit} tokens")
