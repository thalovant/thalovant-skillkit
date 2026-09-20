"""Reference implementation of the OVOS formal specifications.

`ovos-spec-tools` provides the low-level, dependency-light primitives the OVOS
formal specifications describe:

- :func:`~ovos_spec_tools.expansion.expand` — the OVOS-INTENT-1 sentence
  template expander;
- :class:`~ovos_spec_tools.resources.LocaleResources` — the OVOS-INTENT-2
  locale resource-file loader;
- :func:`~ovos_spec_tools.dialog.render` / :class:`~ovos_spec_tools.dialog.DialogRenderer`
  — the OVOS-INTENT-2 §4.2 dialog renderer;
- :func:`~ovos_spec_tools.prompt.render_prompt` / :class:`~ovos_spec_tools.prompt.PromptRenderer`
  — the OVOS-INTENT-2 §4.4 ``.prompt`` renderer;
- :func:`~ovos_spec_tools.language.standardize_lang`,
  :func:`~ovos_spec_tools.language.lang_distance`,
  :func:`~ovos_spec_tools.language.lang_matches`, and
  :func:`~ovos_spec_tools.language.closest_lang` — language-tag normalization,
  distance, match checking, and closest-match resolution;
- :func:`~ovos_spec_tools.resources.iter_locale_dirs` — locale subdirectory
  discovery with optional native-language filtering;
- :func:`~ovos_spec_tools.resources.keyword_form`,
  :func:`~ovos_spec_tools.resources.utterance_contains`,
  :func:`~ovos_spec_tools.resources.strip_samples` — slot-free template
  grouping (§4.3) and utterance match / strip primitives;
- :class:`~ovos_spec_tools.message.Message` — the OVOS-MSG-1 bus message
  envelope with the ``forward`` / ``reply`` / ``response`` derivations;
- :class:`~ovos_spec_tools.session.Session` — the OVOS-SESSION-1 session
  carrier reference implementation, carrying the full §3 registered field
  set with omission-not-null serialization and the
  OVOS-PIPELINE-1 §7.1 / OVOS-CONVERSE-1 §2.1 / §2.2 handler-list helpers;
- :class:`~ovos_spec_tools.intent.IntentBuilder` /
  :class:`~ovos_spec_tools.intent.Intent` — the adapt-free, plugin-agnostic
  keyword intent-definition primitives mapping to the OVOS-INTENT-4 §5 keyword
  registration model, with :func:`~ovos_spec_tools.intent.open_intent_envelope`
  and the :func:`~ovos_spec_tools.intent.voc_match` ``.voc`` matching helper;
- :func:`~ovos_spec_tools.intent_topics.canonical_intent_topic` /
  :func:`~ovos_spec_tools.intent_topics.legacy_intent_topic` — canonical
  ``<skill_id>:<intent_name>`` dispatch topics (OVOS-MSG-1 §2.1.1) and the
  transitional translation to and from the legacy ``.intent``-suffixed
  spelling;
- :func:`~ovos_spec_tools.lint.lint_locale` — a locale resource linter, also
  exposed as the ``ovos-spec-lint`` command.
"""
from ovos_spec_tools.dialog import (
    DialogRenderer,
    UnfilledSlot,
    render,
    verify_slot_consistency,
)
from ovos_spec_tools.expansion import (REGISTERED_TYPES, MalformedTemplate,
                                       expand, inline_keywords, iter_expand)
from ovos_spec_tools.message import (
    DEFAULT_SESSION_ID,
    MalformedMessage,
    Message,
)
from ovos_spec_tools.language import (
    closest_lang,
    lang_distance,
    lang_matches,
    standardize_lang,
)
from ovos_spec_tools.intent import (
    Intent,
    IntentBuilder,
    MalformedIntent,
    MalformedTypedSlots,
    drop_unregistered_typed_slots,
    open_intent_envelope,
    validate_typed_slots,
    voc_match,
)
from ovos_spec_tools.intent_topics import (
    INTENT_FILE_SUFFIX,
    NON_SKILL_NAMESPACES,
    RESERVED_INTENT_NAMES,
    canonical_intent_topic,
    intent_topic_counterpart,
    is_intent_topic,
    legacy_intent_topic,
)
from ovos_spec_tools.lint import (
    Finding,
    declared_slots,
    declared_slot_types,
    lint_locale,
    lint_required_slots,
    lint_slot_types,
    validate_required_slots,
    validate_slot_types,
)
from ovos_spec_tools.messages import (
    MIGRATION_MAP,
    MIGRATION_PAYLOAD_TRANSFORMS,
    SPEC_TO_LEGACY,
    NamespaceTranslator,
    SpecMessage,
    migration_counterpart,
    mirror_counterpart,
)
from ovos_spec_tools.context import (
    gate_satisfied,
    context_supplied_slots,
    context_slot_candidates,
    normalize_declaration,
    resolve_key,
    is_live,
    prune,
    decrement,
    enforce_cap,
)
from ovos_spec_tools.prompt import PromptRenderer, render_prompt
from ovos_spec_tools.session import (
    DEFAULT_CONVERSE_HANDLERS_CAP,
    MalformedSession,
    SESSION1_OWNED_FIELDS,
    SESSION1_REGISTERED_FIELDS,
    Session,
)
from ovos_spec_tools.resources import (
    LocaleResources,
    MalformedResource,
    find_lang_dir,
    iter_locale_dirs,
    keyword_form,
    normalize_for_match,
    read_prompt_file,
    read_resource_file,
    strip_samples,
    utterance_contains,
)
from ovos_spec_tools.version import __version__

__all__ = [
    "Message",
    "MalformedMessage",
    "DEFAULT_SESSION_ID",
    "Session",
    "MalformedSession",
    "SESSION1_OWNED_FIELDS",
    "SESSION1_REGISTERED_FIELDS",
    "DEFAULT_CONVERSE_HANDLERS_CAP",
    "Intent",
    "IntentBuilder",
    "MalformedTypedSlots",
    "drop_unregistered_typed_slots",
    "open_intent_envelope",
    "validate_typed_slots",
    "voc_match",
    "INTENT_FILE_SUFFIX",
    "canonical_intent_topic",
    "is_intent_topic",
    "legacy_intent_topic",
    "expand",
    "inline_keywords",
    "MalformedTemplate",
    "REGISTERED_TYPES",
    "declared_slot_types",
    "lint_slot_types",
    "validate_slot_types",
    "LocaleResources",
    "MalformedResource",
    "find_lang_dir",
    "iter_locale_dirs",
    "keyword_form",
    "normalize_for_match",
    "read_resource_file",
    "read_prompt_file",
    "strip_samples",
    "utterance_contains",
    "render",
    "DialogRenderer",
    "verify_slot_consistency",
    "UnfilledSlot",
    "render_prompt",
    "PromptRenderer",
    "standardize_lang",
    "lang_distance",
    "lang_matches",
    "closest_lang",
    "lint_locale",
    "declared_slots",
    "validate_required_slots",
    "lint_required_slots",
    "Finding",
    "SpecMessage",
    "MIGRATION_MAP",
    "MIGRATION_PAYLOAD_TRANSFORMS",
    "SPEC_TO_LEGACY",
    "migration_counterpart",
    "mirror_counterpart",
    "intent_topic_counterpart",
    "NON_SKILL_NAMESPACES",
    "RESERVED_INTENT_NAMES",
    "NamespaceTranslator",
    "__version__",
]
