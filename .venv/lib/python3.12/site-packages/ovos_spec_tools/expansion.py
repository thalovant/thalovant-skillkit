"""Reference expander for OVOS-INTENT-1 — the Sentence Template Grammar.

This module is the reference implementation of the **Expander** conformance
role of OVOS-INTENT-1 version 2. It turns a *sentence template* into its
**sample set**: the finite set of sample sentences the template denotes.

The grammar has four tokens:

- literal words;
- ``(a|b|c)`` alternatives;
- ``[x]`` optional segments, equivalent to ``(x|)``;
- ``{name}`` named slots — opaque, carried through unchanged, never expanded.
  The double-brace form ``{{name}}`` is an **equivalent** spelling of the same
  named slot (OVOS-INTENT-1 §3.4): ``{name}`` and ``{{name}}`` denote the same
  slot, so a template may use either spelling and the resulting sample set is
  identical. A slot MAY also carry a **type prefix**, ``{type:name}`` /
  ``{{type:name}}`` (§3.4): the slot's name is still ``name``, and expansion
  emits every slot in its bare ``{name}`` form regardless of whether a prefix
  was written (§4.1), so a typed and an untyped template yield the identical
  sample set;
- ``<name>`` inline vocabulary references — replaced, before expansion, by a
  named slot-free vocabulary (OVOS-INTENT-1 §3.7).

Input is assumed to be already ASR-normalized (OVOS-INTENT-1 §2): lowercase,
alphanumeric word tokens separated by single spaces. This module does **not**
normalize; it expands.

Malformed templates (OVOS-INTENT-1 §3.6) raise :class:`MalformedTemplate`.
"""
from __future__ import annotations

import logging
import re
from typing import Iterator, Dict, List, Optional, Sequence, Tuple

__all__ = ["expand", "fold_double_braces", "strip_type_prefixes",
          "MalformedTemplate", "REGISTERED_TYPES"]

_log = logging.getLogger(__name__)

# The seven registered typed-slot types (OVOS-INTENT-1 §5.6). Closed set: a
# type outside it is unregistered and degrades to an untyped slot (§3.6).
REGISTERED_TYPES = ("number", "duration", "date", "color",
                    "language", "location", "timezone")

# A slot or vocabulary name: lowercase ASCII letters, digits, underscores;
# never beginning with a digit (OVOS-INTENT-1 §3.4).
_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
# A named-slot token and an inline-vocabulary-reference token. The interiors
# forbid the matching bracket so a malformed/nested token cannot be matched.
_SLOT_TOKEN_RE = re.compile(r"\{([^{}]*)\}")
_VOC_TOKEN_RE = re.compile(r"<([^<>]*)>")
# The double-brace slot spelling ``{{name}}`` (OVOS-INTENT-1 §3.4) — an
# equivalent form of the single-brace named slot. It is folded to ``{name}``
# before any other parsing. The interior forbids braces so the token is flat,
# and the form is matched here (and folded) **before** the single-brace token
# is ever considered, so ``{{x}}`` is read as one slot and never mis-parsed as
# ``{`` + ``{x}`` + ``}``.
_DOUBLE_SLOT_TOKEN_RE = re.compile(r"\{\{([^{}]*)\}\}")
# A well-formed type prefix on a slot token: `type:name`, both halves obeying
# the §3.4 charset. Matched strictly so a malformed prefix (`number:`, `:x`,
# `a:b:c`) is left untouched here and falls through to `_check_names`, which
# rejects it via the ordinary name-charset check (its content still contains
# a bare `:`, which no valid name may contain).
_TYPE_PREFIX_RE = re.compile(r"\A([a-z][a-z0-9_]*):([a-z][a-z0-9_]*)\Z")
# Two named slots in a sample with only whitespace between them.
_ADJACENT_SLOTS_RE = re.compile(r"\}\s*\{")


class MalformedTemplate(ValueError):
    """A template that violates OVOS-INTENT-1 §3.6.

    Raised for unbalanced metacharacters, single-branch groups, empty samples,
    slot-only templates, adjacent slots, repeated slot names, and undefined or
    cyclic vocabulary references.
    """


def expand(template: str,
           vocabularies: Optional[Dict[str, Sequence[str]]] = None) -> List[str]:
    """Expand a template to its sample set (OVOS-INTENT-1 §4).

    Args:
        template: a sentence template in the OVOS-INTENT-1 grammar.
        vocabularies: maps a vocabulary name to its members — a sequence of
            slot-free templates (the lines of a ``.voc``). Required only if
            ``template`` contains ``<name>`` references.

    Returns:
        The sample set: distinct sample sentences, in first-seen order. Each
        is a single-spaced string of literal words and opaque ``{name}`` slots.

    Raises:
        MalformedTemplate: if the template (or a referenced vocabulary) is
            malformed per OVOS-INTENT-1 §3.6.
    """
    return _expand(template, dict(vocabularies or {}), ())


def _expand(template: str,
            vocabularies: Dict[str, Sequence[str]],
            stack: Tuple[str, ...]) -> List[str]:
    """Expand ``template``; ``stack`` is the chain of vocabularies being
    resolved, for cycle detection."""
    if not isinstance(template, str):
        raise MalformedTemplate(f"template must be a string, got {type(template)!r}")

    # Fold the double-brace slot spelling ``{{name}}`` to the canonical
    # single-brace ``{name}`` (OVOS-INTENT-1 §3.4) before any other parsing,
    # so the two spellings are exactly equivalent and every downstream check
    # (balance, names, slot-only, adjacency, repetition) sees one slot form.
    # Done first — and matching the double form before the single — so
    # ``{{x}}`` is never mis-read as ``{`` + ``{x}`` + ``}``.
    template = fold_double_braces(template)
    template = strip_type_prefixes(template)

    _check_balanced(template)
    _check_names(template)

    # Slot-only template (§3.6): the whole template is a single named slot.
    if _SLOT_TOKEN_RE.fullmatch(template.strip()):
        raise MalformedTemplate(
            f"slot-only template {template!r}: a template must carry at least "
            f"one literal word")

    return list(_iter_expand(template, vocabularies, stack))


def iter_expand(template: str,
                vocabularies: Optional[Dict[str, Sequence[str]]] = None
                ) -> Iterator[str]:
    """Lazily expand a template to its sample set (OVOS-INTENT-1 §4).

    Yields exactly the samples ``expand`` returns, in the same first-seen
    order, WITHOUT materializing the Cartesian product: a consumer that
    needs only the first N samples of a combinatorially large template
    (``itertools.islice``) pays for N, not for the full product. Validation
    behaves as in ``expand``: template-level malformedness raises before the
    first yield; per-sample checks raise when the offending sample is
    reached.
    """
    yield from _iter_expand(template, dict(vocabularies or {}), ())


def _iter_expand(template: str,
                 vocabularies: Dict[str, Sequence[str]],
                 stack: Tuple[str, ...]) -> Iterator[str]:
    if not isinstance(template, str):
        raise MalformedTemplate(f"template must be a string, got {type(template)!r}")
    template = fold_double_braces(template)
    template = strip_type_prefixes(template)
    _check_balanced(template)
    _check_names(template)
    if _SLOT_TOKEN_RE.fullmatch(template.strip()):
        raise MalformedTemplate(
            f"slot-only template {template!r}: a template must carry at least "
            f"one literal word")
    resolved = _resolve_references(template, vocabularies, stack)
    converted = _convert_optionals(resolved)
    folded = _fold_single_branch_groups(converted)
    seen = set()
    for sentence in _iter_groups(folded):
        sentence = " ".join(sentence.split())  # normalize whitespace (§4.1)
        if sentence in seen:  # remove duplicates (§4.1)
            continue
        seen.add(sentence)
        _check_sample(sentence, template)
        yield sentence


def fold_double_braces(template: str) -> str:
    """Fold every ``{{name}}`` to the equivalent ``{name}`` (§3.4).

    The double-brace spelling is matched and replaced **before** the
    single-brace token is ever examined, so ``{{x}}`` collapses to ``{x}`` as
    a single slot rather than being read as ``{`` + ``{x}`` + ``}``. The
    interior is carried through verbatim, so an ill-formed interior survives
    to be rejected by the same §3.4 name check that guards ``{name}``.
    """
    return _DOUBLE_SLOT_TOKEN_RE.sub(lambda m: "{" + m.group(1) + "}", template)


def strip_type_prefixes(template: str) -> str:
    """Strip a well-formed ``type:`` prefix off every slot, folding it to
    ``{name}`` (§3.4, §4.1).

    Runs after :func:`fold_double_braces`, so both brace spellings reach this
    as ``{type:name}``. A slot whose type is not one of :data:`REGISTERED_TYPES`
    degrades the same way — the prefix is stripped and a warning logged
    (§3.6) — because the degrade rule makes an unregistered type exactly as
    portable as no type at all. A malformed prefix (empty type, empty name, or
    more than one colon) does not match :data:`_TYPE_PREFIX_RE` and is left
    untouched, to be rejected by :func:`_check_names`'s ordinary charset check.
    """
    def _fold(match: "re.Match[str]") -> str:
        content = match.group(1)
        prefix = _TYPE_PREFIX_RE.match(content)
        if prefix is None:
            return match.group(0)
        slot_type, name = prefix.groups()
        if slot_type not in REGISTERED_TYPES:
            _log.warning(
                "OVOS-INTENT-1 §3.6: unregistered type prefix %r on slot "
                "{%s}; degrading to the untyped slot {%s}",
                slot_type, content, name)
        return "{" + name + "}"

    return _SLOT_TOKEN_RE.sub(_fold, template)


def _check_balanced(template: str) -> None:
    """Reject unbalanced or malformed metacharacters (§3.6)."""
    # `{name}` and `<name>` are flat tokens — they do not nest. Strip every
    # well-formed token; any bracket left behind is unbalanced or nested.
    residue = _SLOT_TOKEN_RE.sub(" ", template)
    if "{" in residue or "}" in residue:
        raise MalformedTemplate(
            f"unbalanced or nested braces in template {template!r}")
    residue = _VOC_TOKEN_RE.sub(" ", residue)
    if "<" in residue or ">" in residue:
        raise MalformedTemplate(
            f"unbalanced or nested angle brackets in template {template!r}")

    # `(...)` and `[...]` nest; check with a stack.
    opener = {")": "(", "]": "["}
    stack: List[str] = []
    for char in template:
        if char in "([":
            stack.append(char)
        elif char in ")]":
            if not stack or stack[-1] != opener[char]:
                raise MalformedTemplate(
                    f"unbalanced metacharacters in template {template!r}")
            stack.pop()
    if stack:
        raise MalformedTemplate(
            f"unbalanced metacharacters in template {template!r}")


def _check_names(template: str) -> None:
    """Reject slot or vocabulary names outside the §3.4 charset."""
    for match in _SLOT_TOKEN_RE.finditer(template):
        if not _NAME_RE.fullmatch(match.group(1)):
            raise MalformedTemplate(
                f"invalid slot name {{{match.group(1)}}}: a name is lowercase "
                f"letters, digits and underscores, not beginning with a digit")
    for match in _VOC_TOKEN_RE.finditer(template):
        if not _NAME_RE.fullmatch(match.group(1)):
            raise MalformedTemplate(
                f"invalid vocabulary name <{match.group(1)}>: a name is "
                f"lowercase letters, digits and underscores, not beginning "
                f"with a digit")


def _resolve_references(template: str,
                        vocabularies: Dict[str, Sequence[str]],
                        stack: Tuple[str, ...]) -> str:
    """Resolve every ``<name>`` (§4.1 step 1), recursively, leftmost first."""
    while True:
        match = _VOC_TOKEN_RE.search(template)
        if match is None:
            return template
        name = match.group(1)

        if name in stack:
            raise MalformedTemplate(
                f"cyclic vocabulary reference <{name}> "
                f"(chain: {' -> '.join(stack + (name,))})")
        if name not in vocabularies:
            raise MalformedTemplate(f"undefined vocabulary reference <{name}>")

        members: List[str] = []
        for member_template in vocabularies[name]:
            for member in _expand(member_template, vocabularies, stack + (name,)):
                if "{" in member or "}" in member:
                    raise MalformedTemplate(
                        f"vocabulary <{name}> is not slot-free: member "
                        f"{member!r} contains a named slot")
                if member not in members:
                    members.append(member)
        if not members:
            raise MalformedTemplate(f"empty vocabulary <{name}>")

        # A single-member vocabulary substitutes its bare member; two or more
        # substitute as an alternatives group.
        if len(members) == 1:
            substitution = members[0]
        else:
            substitution = "(" + "|".join(members) + ")"
        template = template[:match.start()] + substitution + template[match.end():]


def _convert_optionals(template: str) -> str:
    """Replace every ``[x]`` with ``(x|)`` (§4.1 step 2)."""
    while "[" in template:
        open_idx = template.rfind("[")
        close_idx = template.find("]", open_idx)
        inner = template[open_idx + 1:close_idx]
        template = (template[:open_idx] + "(" + inner + "|)"
                    + template[close_idx + 1:])
    return template


def _fold_single_branch_groups(template: str) -> str:
    """Fold every single-branch group to its bare branch (§3.6).

    A single-branch group ``(word)`` is degenerate, not malformed:
    ``(word)`` == ``word``. OVOS-INTENT-1 §3.5: "Expansion groups MAY be
    nested without limit." Folding runs bottom-up: an inner group's ``)``
    closes (and is folded or left as a kept multi-branch group) before its
    enclosing group's own branch count is read off the text, so a `|`
    belonging to a nested, already-resolved group is never mistaken for
    the enclosing group's own separator. Doing this before any multi-
    branch group is expanded also means each syntactic occurrence, at
    whatever depth, warns exactly once — folding after branching would
    warn once per branch of every enclosing multi-branch group instead.
    """
    output: List[str] = []
    stack: List[List[str]] = []
    current = output
    for char in template:
        if char == "(":
            stack.append(current)
            current = []
        elif char == ")":
            inner = "".join(current)
            current = stack.pop()
            if "|" in inner:
                current.append("(" + inner + ")")
            elif inner.strip() == "":
                raise MalformedTemplate(
                    f"empty group ({inner}) is malformed (OVOS-INTENT-1 "
                    f"§3.6): its one branch is the empty string, so the "
                    f"group expresses no choice at all")
            else:
                _log.warning(
                    "OVOS-INTENT-1 §3.6: single-branch group (%s) is "
                    "degenerate; treating as the bare branch %r", inner, inner)
                current.append(inner)
        else:
            current.append(char)
    return "".join(output)


def _iter_groups(template: str) -> Iterator[str]:
    """Yield every ``(...)`` group combination lazily, product order.

    Every group reaching this point already has two or more branches —
    :func:`_fold_single_branch_groups` folds the degenerate ones first.
    """
    open_idx = template.rfind("(")
    if open_idx == -1:
        yield template
        return
    close_idx = template.find(")", open_idx)
    inner = template[open_idx + 1:close_idx]
    prefix = template[:open_idx]
    suffix = template[close_idx + 1:]
    for branch in inner.split("|"):
        yield from _iter_groups(prefix + branch + suffix)


def _check_sample(sentence: str, template: str) -> None:
    """Reject a sample that is malformed per §3.6."""
    if sentence == "":
        raise MalformedTemplate(
            f"template {template!r} yields an empty sample")
    if _ADJACENT_SLOTS_RE.search(sentence):
        raise MalformedTemplate(
            f"adjacent slots in sample {sentence!r} of template {template!r}: "
            f"a literal word must separate any two slots")
    names = _SLOT_TOKEN_RE.findall(sentence)
    if len(names) != len(set(names)):
        raise MalformedTemplate(
            f"repeated slot name in sample {sentence!r} of template "
            f"{template!r}: each slot is defined once per sample")


def inline_keywords(
    template: str,
    vocabularies: Dict[str, Sequence[str]] | None = None,
    *,
    max_values: Optional[int] = None,
) -> str:
    """Inline ``<keyword>`` references as ``(v1|v2|…)`` alternation groups.

    Partial application of OVOS-INTENT-1 §4.1 step 1 (resolve ``<name>``
    references) that stops **before** the rest of expansion: §3.7 / §4.1 define
    a ``<name>`` reference as equivalent to the alternative group of the
    vocabulary's members written in its place, and this returns exactly that
    rewritten *template* rather than the fully enumerated sample set. It exists
    because engines like Padatious do not look up ``.voc`` files at runtime —
    they need keywords baked into the template body as standard ``(a|b|c)``
    alternations, then expand the result themselves.

    Unlike :func:`expand`, this is intentionally lenient and **not** a
    conformant expander: it does no §3.6 validation and leaves an unknown
    keyword's angle brackets stripped as literal text rather than raising
    :class:`MalformedTemplate` for an undefined reference. Feed its output to
    :func:`expand` for the validated sample set.

    By default **every** value of a keyword is inlined (no silent truncation).
    Resolution recurses through nested references — ``<a>`` inside ``<b>`` — and
    a reference cycle raises :class:`MalformedTemplate` per OVOS-INTENT-1 §4.1,
    rather than being cut off at an arbitrary depth.

    Parameters
    ----------
    template
        Template string with ``<keyword>`` references.
    vocabularies
        Flat ``{keyword: [values]}`` mapping.  If ``None`` or empty the
        template is returned unchanged.
    max_values
        Optional bound on the number of values inlined per keyword. ``None``
        (the default) inlines **all** values. OVOS-INTENT-1 §4.3 permits an
        expander to *refuse* (not silently drop) a template whose expansion
        exceeds a documented limit; accordingly, when a keyword has more than
        ``max_values`` members this **raises** :class:`MalformedTemplate`. It
        never silently truncates the value list.

    Returns
    -------
    str
        Template with all ``<keyword>`` references inlined as ``(a|b|c)``
        groups.  Keywords not found in ``vocabularies`` have their angle
        brackets stripped and become literal text.

    Raises
    ------
    MalformedTemplate
        On a reference cycle (OVOS-INTENT-1 §4.1), or when a keyword's value
        count exceeds an explicit ``max_values`` bound (OVOS-INTENT-1 §4.3,
        refuse-and-document).

    Example
    -------
    >>> inline_keywords("<turn_on> [the] {name}",
    ...                 {"turn_on": ["turn on", "switch on"]})
    '(turn on|switch on) [the] {name}'
    """
    if not vocabularies:
        return template
    return _inline_keywords(template, vocabularies, max_values, ())


def _inline_keywords(template: str,
                     vocabularies: Dict[str, Sequence[str]],
                     max_values: Optional[int],
                     stack: Tuple[str, ...]) -> str:
    """Resolve ``<name>`` references recursively, leftmost first, with cycle
    detection (OVOS-INTENT-1 §4.1). ``stack`` is the chain of references being
    resolved; a name already on it is a cycle and is rejected."""
    while True:
        match = _VOC_TOKEN_RE.search(template)
        if match is None:
            return template
        name = match.group(1)

        if name in stack:
            raise MalformedTemplate(
                f"cyclic vocabulary reference <{name}> "
                f"(chain: {' -> '.join(stack + (name,))})")

        vals = vocabularies.get(name)
        if not vals:
            # Lenient: an unknown keyword is left as literal text (brackets
            # stripped) rather than raising. Skip past it so the leftmost-first
            # scan continues and an undefined reference cannot loop forever.
            template = (template[:match.start()] + name
                        + template[match.end():])
            continue

        if max_values is not None and len(vals) > max_values:
            # §4.3 permits a documented limit enforced by REFUSING — never by
            # silently dropping values (which would be data loss).
            raise MalformedTemplate(
                f"vocabulary <{name}> has {len(vals)} values, exceeding the "
                f"max_values bound of {max_values} (OVOS-INTENT-1 §4.3: a limit "
                f"is enforced by refusing, not by truncating)")

        # Resolve any nested references inside each value before substituting,
        # carrying this name on the stack for cycle detection.
        resolved_vals = [
            _inline_keywords(v, vocabularies, max_values, stack + (name,))
            for v in vals
        ]
        substitution = "(" + "|".join(resolved_vals) + ")"
        template = (template[:match.start()] + substitution
                    + template[match.end():])
