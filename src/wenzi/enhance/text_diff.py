"""Shared inline-diff utilities for comparing ASR and corrected text."""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import List

# ASCII words as whole units, each non-ASCII char individually,
# whitespace runs, or any other single character.
_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[^\x00-\x7f]|\s+|.")


def tokenize_for_diff(text: str) -> List[str]:
    """Split text into diff-friendly tokens.

    English/number sequences stay as whole tokens; each CJK character
    becomes its own token.  This gives a good granularity for diffing
    mixed Chinese-English ASR text.
    """
    return _TOKEN_RE.findall(text)


def _is_punctuation_only(text: str) -> bool:
    """Return True if *text* consists entirely of punctuation/symbols/whitespace."""
    return bool(text) and all(
        unicodedata.category(ch)[0] in ("P", "S", "Z") for ch in text
    )


def _strip_boundary_punctuation(text: str) -> tuple[str, str, str]:
    """Strip leading/trailing punctuation from *text*.

    Returns ``(leading_punc, core, trailing_punc)``.
    """
    start = 0
    while start < len(text) and unicodedata.category(text[start])[0] in ("P", "S"):
        start += 1
    end = len(text)
    while end > start and unicodedata.category(text[end - 1])[0] in ("P", "S"):
        end -= 1
    return text[:start], text[start:end], text[end:]


def _merge_adjacent_opcodes(
    opcodes: List[tuple],
    asr_tokens: List[str],
    final_tokens: List[str],
) -> List[tuple]:
    """Merge a delete immediately followed by a replace (or vice versa).

    When SequenceMatcher produces ``delete + equal(whitespace/punc) + replace``
    or ``delete + replace``, the delete portion is semantically part of the
    same user correction.  Merge them into a single replace so the deleted
    text is not silently lost.  Same logic applies for ``replace + equal + delete``
    and ``replace + delete``.
    """
    merged: List[tuple] = list(opcodes)
    changed = True
    while changed:
        changed = False
        new: List[tuple] = []
        i = 0
        while i < len(merged):
            op, i1, i2, j1, j2 = merged[i]

            if i + 1 < len(merged):
                nop, ni1, ni2, nj1, nj2 = merged[i + 1]

                # delete + replace → single replace
                if op == "delete" and nop == "replace":
                    new.append(("replace", i1, ni2, j1, nj2))
                    i += 2
                    changed = True
                    continue

                # replace + delete → single replace
                if op == "replace" and nop == "delete":
                    new.append(("replace", i1, ni2, j1, nj2))
                    i += 2
                    changed = True
                    continue

                # delete + equal(punc/whitespace only) + replace → single replace
                if op == "delete" and nop == "equal" and i + 2 < len(merged):
                    nnop, nni1, nni2, nnj1, nnj2 = merged[i + 2]
                    gap = "".join(asr_tokens[ni1:ni2])
                    if nnop == "replace" and _is_punctuation_only(gap):
                        new.append(("replace", i1, nni2, j1, nnj2))
                        i += 3
                        changed = True
                        continue

                # replace + equal(punc/whitespace only) + delete → single replace
                if op == "replace" and nop == "equal" and i + 2 < len(merged):
                    nnop, nni1, nni2, nnj1, nnj2 = merged[i + 2]
                    gap = "".join(asr_tokens[ni1:ni2])
                    if nnop == "delete" and _is_punctuation_only(gap):
                        new.append(("replace", i1, nni2, j1, nnj2))
                        i += 3
                        changed = True
                        continue

            new.append(merged[i])
            i += 1
        merged = new
    return merged


def inline_diff(asr: str, final: str) -> str:
    """Produce an inline diff between ASR text and corrected text.

    Only replacements are bracketed as ``[old→new]``.  Insertions
    and deletions are applied silently (new text included / old text
    omitted) since they carry no ASR-misrecognition information
    useful for vocabulary extraction.

    Adjacent delete + replace sequences are merged into a single
    replacement so that deleted tokens are not silently lost.

    Punctuation-only replacements (e.g. half-width to full-width
    ``[,→，]``) are also applied silently — they are ASR/input-method
    artifacts, not meaningful corrections.  Boundary punctuation on
    replacement content is stripped outside the brackets.
    """
    if asr == final:
        return asr

    asr_tokens = tokenize_for_diff(asr)
    final_tokens = tokenize_for_diff(final)
    matcher = difflib.SequenceMatcher(None, asr_tokens, final_tokens)
    opcodes = _merge_adjacent_opcodes(
        matcher.get_opcodes(), asr_tokens, final_tokens,
    )

    parts: List[str] = []
    for op, i1, i2, j1, j2 in opcodes:
        if op == "equal":
            parts.append("".join(asr_tokens[i1:i2]))
        elif op == "replace":
            old_raw = "".join(asr_tokens[i1:i2])
            new_raw = "".join(final_tokens[j1:j2])
            if _is_punctuation_only(old_raw) and _is_punctuation_only(new_raw):
                parts.append(new_raw)
            else:
                # Strip whitespace
                old_ws = old_raw.strip()
                new_ws = new_raw.strip()
                leading = new_raw[: len(new_raw) - len(new_raw.lstrip())]
                trailing = new_raw[len(new_raw.rstrip()) :]
                # Strip boundary punctuation from old/new
                old_lead_p, old, old_trail_p = _strip_boundary_punctuation(old_ws)
                new_lead_p, new, new_trail_p = _strip_boundary_punctuation(new_ws)
                if not old and not new:
                    # Both sides are punctuation-only after stripping
                    parts.append(f"{leading}{new_ws}{trailing}")
                elif not old:
                    # Old side became empty — treat as insertion
                    parts.append(f"{leading}{new_ws}{trailing}")
                else:
                    parts.append(
                        f"{leading}{old_lead_p}[{old}→{new}]{new_trail_p}{trailing}"
                    )
        elif op == "insert":
            parts.append("".join(final_tokens[j1:j2]))
        # delete: omit old text silently
    return "".join(parts)
