# # NEON AI (TM) SOFTWARE, Software Development Kit & Application Development System
# # All trademark and other rights reserved by their respective owners
# # Copyright 2008-2021 Neongecko.com Inc.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived from this
#    software without specific prior written permission.
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
# PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
# CONTRIBUTORS  BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
# OR PROFITS;  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE,  EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
from os.path import join, dirname
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ovos_plugin_manager.templates.transformers import UtteranceTransformer
from ovos_spec_tools import LocaleResources, standardize_lang
from ovos_utils.log import LOG


def _resolve_lang(context: Optional[Dict[str, object]],
                  default: str = "en-US") -> str:
    """Return the BCP-47 language tag for an UtteranceTransformer call.

    ``context`` is the OVOS-MSG-1 ``message.context`` dict the
    transformer service hands to ``transform()``. Two sources may carry
    a language:

    1. ``context["lang"]`` — the top-level convenience key that
       ovos-core's IntentService writes before invoking transformers
       (``ovos_core/intent_services/service.py::_handle_transformers``).
       This is the **current contract** between core and transformer
       plugins; trust it when present.
    2. ``context["session"]["lang"]`` — the normative session-carrier
       field per OVOS-MSG-1 §4. Falls back here when a caller hands the
       transformer a Message without going through ovos-core's
       pre-processing (HiveMind relays, tests, alternative bus
       clients).

    The convenience top-level key is a known gap in the spec — the
    transformer signature will likely grow an explicit ``lang`` kwarg
    in a future revision, at which point this helper collapses to a
    one-liner. Until then, the dual lookup keeps the plugin robust
    against direct callers.

    ``dict.get(key, default)`` returns ``None`` for keys present with a
    ``None`` value (only a *missing* key triggers the default), so the
    ``or`` chain handles explicit ``None`` correctly.
    """
    context = context or {}
    session = context.get("session") or {}
    lang = (context.get("lang")
            or session.get("lang")
            or default)
    return standardize_lang(lang)


class NevermindPlugin(UtteranceTransformer):
    """Utterance transformer that drops utterances ending with a cancel phrase.

    Cancel phrases are loaded from ``locale/<lang>/cancel.voc`` and
    matched against the tail of each utterance.  On a match the utterance
    list is cleared and ``{"canceled": True, "cancel_word": <phrase>}`` is
    added to the context dict so downstream components can react.
    """

    def __init__(self, name: str = "ovos-utterance-cancel", priority: int = 15) -> None:
        super().__init__(name, priority)
        # OVOS-INTENT-2 resource loader. One instance serves every language
        # the plugin ships; the language is a parameter of each load call.
        # The default lang_resolver is `closest_lang` (OVOS-INTENT-2 §2.2
        # smart fallback), gated on distance < 10.
        self._resources = LocaleResources(
            skill_locale=join(dirname(__file__), "locale"))

    @lru_cache()
    def get_cancel_words(self, lang: str = "en-US") -> List[str]:
        """Return the cancel phrases for *lang* (``cancel.voc``)."""
        try:
            phrases = self._resources.load_vocabulary("cancel", lang)
        except FileNotFoundError:
            LOG.warning(f"cancel.voc not available for {lang}")
            return []
        return list({phrase.strip() for phrase in phrases if phrase.strip()})

    @lru_cache()
    def get_cancel_blacklist(self, lang: str = "en-US") -> List[str]:
        """Return the *veto prefixes* for *lang* (``cancel.blacklist``).

        OVOS-INTENT-2 §4.3 defines ``.blacklist`` as a phrase set that
        an engine consults to *exclude* matches. Here, utterances that
        start with any phrase in ``cancel.blacklist`` bypass the cancel
        suffix match — they are *about* a cancel word (define / spell /
        pronounce / play / etc.) rather than commands to cancel.
        Partial fix for issue #7. A missing ``cancel.blacklist`` is
        non-fatal: the plugin falls back to the historic
        "always check the suffix" behaviour.
        """
        try:
            phrases = self._resources.load_blacklist("cancel", lang)
        except FileNotFoundError:
            return []
        return list({phrase.strip() for phrase in phrases if phrase.strip()})

    def transform(
        self,
        utterances: List[str],
        context: Optional[Dict[str, object]] = None,
    ) -> Tuple[List[str], Dict[str, object]]:
        """Drop utterances that end with a cancel phrase.

        Skipped when the utterance starts with a phrase listed in
        ``cancel.blacklist`` for the active language — partial veto for
        the edge cases tracked in issue #7 (e.g. ``"say nevermind"``,
        ``"what is the opposite of nevermind"``).

        Args:
            utterances: Recognised utterance candidates.
            context: Session context dict; ``lang`` key is used for locale
                selection (defaults to ``"en-US"`` when absent).

        Returns:
            A 2-tuple of ``(utterances, extra_context)``.  When a cancel phrase
            is matched, *utterances* is empty and *extra_context* contains
            ``{"canceled": True, "cancel_word": <phrase>}``.  Otherwise the
            original utterances are returned unchanged with an empty dict.
        """
        lang = _resolve_lang(context)
        blacklist = self.get_cancel_blacklist(lang)
        for nevermind in self.get_cancel_words(lang):
            for utterance in utterances:
                if any(utterance.startswith(p) for p in blacklist):
                    continue
                if utterance.endswith(nevermind):
                    return [], {"canceled": True, "cancel_word": nevermind}
        return utterances, {}
