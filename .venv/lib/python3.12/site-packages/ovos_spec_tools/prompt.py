"""Reference prompt renderer for OVOS-INTENT-2 §4.4.

A ``.prompt`` is the localized, whole-file plain-text prompt a skill feeds to a
language model. Unlike a ``.dialog`` it is **not** a sentence template: none of
the OVOS-INTENT-1 grammar applies, so ``(``, ``[``, ``|`` and the rest are
literal. The one special construct is the **double-brace** ``{{name}}``
substitution point, and it is applied **conservatively** — a prompt is
free-form text that routinely embeds code and JSON, and rendering it must
never corrupt text the author did not write as a slot.

A ``.prompt`` uses the double-brace form **only** (OVOS-INTENT-2 §4.4): a
single ``{name}`` is **literal text** and is never substituted, as are any
lone ``{`` or ``}``. This is the rationale for the double-brace requirement —
prompts are natural-language LLM text that routinely contains literal single
braces (JSON such as ``{"key": 1}``, code), so a single brace must never
trigger substitution. The single-brace ``{name}`` form (OVOS-INTENT-1 §3.4)
remains the slot token of the *template* roles (``.intent``/``.dialog``); it
has no special meaning in a ``.prompt``.

A ``{{name}}`` is replaced by a caller-supplied value only when all three hold:

1. it is a well-formed double-brace token ``{{name}}`` whose name is lowercase
   ASCII letters, digits and underscores, not beginning with a digit (so
   ``{{}}``, ``{{ }}``, a single ``{name}``, and JSON such as ``{"key": 1}``
   are left untouched). The name charset is identical to the slot-name rule of
   OVOS-INTENT-1 §3.4;
2. the caller supplied a value for that name — an **unfilled** ``{{name}}`` is
   left as literal text, not an error (the deliberate opposite of ``.dialog``,
   where §4.2/OVOS-INTENT-1 §5.1 require **every** slot be filled before TTS);
3. it does not lie inside a ```` ``` ```` fenced code block. Fence detection
   here is a simple heuristic (counting triple backticks): a line whose first
   non-whitespace content is three or more backticks toggles the fence, and an
   unterminated fence extends to end-of-file. Nested/indented fences are
   implementation-defined.

Two interfaces are provided:

- :func:`render_prompt` — a stateless function over an explicit prompt string;
- :class:`PromptRenderer` — a stateful, **multilingual** object backed by a
  :class:`~ovos_spec_tools.resources.LocaleResources`.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

__all__ = ["render_prompt", "PromptRenderer"]

# A {{name}} substitution point — the OVOS-INTENT-2 §4.4 double-brace form,
# the ONLY substitution token in a .prompt. The name uses the §3.4 charset.
# A single-brace {name} is deliberately NOT matched: in a prompt it is literal
# text. The interior of the braces forbids ``{``/``}`` so the token is flat and
# a single ``{name}`` nested inside ``{{ }}`` cannot accidentally extend it.
_SLOT_RE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


def _is_fence(line: str) -> bool:
    """Whether a line opens or closes a ```` ``` ```` fenced code block.

    Implements the OVOS-INTENT-2 §4.4 fence test in its permitted simplified
    form: a line whose first non-whitespace content is three backticks toggles
    the fenced-block state. ``lstrip(" \\t")`` mirrors §4.4's "first
    non-whitespace content"; only the opening delimiter is checked (info
    strings and longer fences are treated the same), which §4.4 allows as a
    "simpler heuristic" so long as well-formed prompts render identically.

    Args:
        line: one line of the prompt, with or without its trailing newline.

    Returns:
        ``True`` if this line is a fence delimiter, else ``False``.
    """
    return line.lstrip(" \t").startswith("```")


def render_prompt(text: str,
                  slots: Optional[Dict[str, object]] = None) -> str:
    """Render a ``.prompt`` string (stateless).

    The whole ``text`` is the prompt; every character is significant.
    ``{{name}}`` substitution points are filled per the rules in the module
    docstring — conservatively, and leaving an unfilled slot as literal text.
    A single-brace ``{name}`` and any literal brace are passed through
    unchanged.

    Args:
        text: the whole-file content of a ``.prompt`` (§4.4 "the whole file,
            verbatim, is one prompt").
        slots: caller-supplied values, keyed by slot name. Values are
            converted to text via ``str()``. A name absent here, any
            malformed ``{{…}}`` (per §4.4 condition 1), and every single-brace
            ``{name}`` are left as literal text — §4.4's "slots are optional"
            and the double-brace-only rule.

    Returns:
        The prompt with its supplied slots substituted, otherwise verbatim —
        byte-for-byte unchanged outside the substituted ``{{name}}`` points
        (``splitlines(keepends=True)`` preserves the original line endings, and
        text inside a fenced block is reproduced untouched). An empty ``text``
        returns ``""``.
    """
    values = slots or {}

    def replace(match: "re.Match") -> str:
        name = match.group(1)
        if name in values:
            return str(values[name])
        return match.group(0)  # an unfilled {{name}} stays literal (§4.4)

    rendered: List[str] = []
    in_fence = False
    # keepends=True so the file is reproduced verbatim apart from substitution.
    for line in text.splitlines(keepends=True):
        if _is_fence(line):
            in_fence = not in_fence
            rendered.append(line)
        elif in_fence:
            rendered.append(line)
        else:
            rendered.append(_SLOT_RE.sub(replace, line))
    return "".join(rendered)


class PromptRenderer:
    """A stateful, multilingual renderer for one named ``.prompt``.

    Backed by a :class:`~ovos_spec_tools.resources.LocaleResources`: the prompt
    name is fixed at construction, but the **language is given per**
    :meth:`render` **call**, so one renderer serves every language the prompt
    is shipped in.

    Unlike :class:`~ovos_spec_tools.dialog.DialogRenderer` it carries no
    randomness and no ``.entity`` fallback — a prompt has a single whole-file
    body and its slots are optional (§4.4). It does hold **default** slot
    values, reused on every call.
    """

    def __init__(self, resources, name: str,
                 slots: Optional[Dict[str, object]] = None):
        """
        Args:
            resources: a :class:`~ovos_spec_tools.resources.LocaleResources`
                (or anything with a ``load_prompt(name, lang)`` method).
            name: the base name of the ``.prompt`` to render.
            slots: **default** slot values, held for the renderer's lifetime
                and reused on every :meth:`render` call. A per-call value
                overrides a default.
        """
        self.resources = resources
        self.name = name
        self.default_slots: Dict[str, object] = dict(slots or {})

    def render(self, lang: str,
               slots: Optional[Dict[str, object]] = None) -> str:
        """Render the prompt in ``lang``.

        Args:
            lang: the BCP-47 language tag to render in.
            slots: per-call slot values; each overrides a default.

        Returns:
            The rendered prompt string.

        Raises:
            FileNotFoundError: the prompt does not exist for ``lang``.
            MalformedResource: the resolved ``.prompt`` file is empty.
        """
        text = self.resources.load_prompt(self.name, lang)
        effective = dict(self.default_slots)
        if slots:
            effective.update(slots)
        return render_prompt(text, effective)
