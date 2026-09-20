from os.path import isfile

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_plugin_manager.templates.transformers import IntentTransformer
from ovos_spec_tools.expansion import expand
from ovos_spec_tools.messages import SpecMessage
from ovos_spec_tools import standardize_lang
from ovos_utils.list_utils import deduplicate_list, flatten_list
from ovos_utils.log import LOG
from typing import Union

from kw_template_matcher import TemplateMatcher


class KeywordTemplateMatcher(IntentTransformer):
    def __init__(self, config=None):
        super().__init__("keyword-templates", 1, config)
        self.matchers = {}
        # OVOS-INTENT-2 §4.3 per-slot value exclusions, keyed by
        # (lang, match_type) so one language's blacklist never stands in for
        # another's (pronoun sets are language specific).
        self.slot_blacklists = {}

    def bind(self, bus):
        super().bind(bus)
        self.bus.on('padatious:register_intent', self.handle_register_intent)
        self.bus.on(SpecMessage.INTENT_REGISTER_TEMPLATE.value,
                    self.handle_register_template)

    def _unpack_object(self, message: Message, name_key: str = 'name',
                        blacklist_key: str = 'blacklisted_words'):
        """convert message to training data"""
        # standard info
        sess = SessionManager.get(message)
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        if not skill_id:
            skill_id = "anonymous_skill"
        lang = message.data.get('lang') or sess.lang
        lang = standardize_lang(lang)

        # intent specific
        file_name = message.data.get('file_name')
        samples = message.data.get("samples")
        name = message.data[name_key]
        blacklisted_words = message.data.get(blacklist_key, [])
        if not samples and not file_name:
            # no samples and no file to load them from -> no-op registration
            # (INTENT-4 §6.3), never a crash
            LOG.warning(f"no samples to register for {name!r} "
                        f"(skill_id={skill_id!r} lang={lang!r} "
                        f"topic={message.msg_type})")
            return lang, skill_id, name, [], blacklisted_words
        if not samples and (not file_name or not isfile(file_name)):
            raise FileNotFoundError('Could not find file ' + file_name)
        if not samples and isfile(file_name):
            with open(file_name) as f:
                samples = [line.strip() for line in f.readlines()]

        # expand templates, skipping malformed ones so a single bad line
        # never prevents the remaining samples from being registered
        # (OVOS-INTENT-4 §6.3); each skip is logged with the §5.3 fields
        ctx = (f"[skill_id={skill_id!r} name={name!r} lang={lang!r} "
               f"topic={message.msg_type}]")
        expanded = []
        skipped = False
        for s in samples:
            try:
                expanded.append(expand(s))
            except Exception as e:
                LOG.warning(f"skipping malformed template {s!r}: {e} {ctx}")
                skipped = True
        samples = deduplicate_list(flatten_list(expanded))
        if skipped and not samples:
            # zero valid templates -> the whole registration is malformed
            LOG.warning(f"rejecting registration: no valid template "
                        f"remains {ctx}")

        # we only care about keyword extractors, drop the rest
        samples = [s for s in samples if "{" in s]

        return lang, skill_id, name, samples, blacklisted_words

    @staticmethod
    def _slot_blacklist(data: dict) -> dict:
        """OVOS-INTENT-2 §4.3 per-slot value exclusions carried by a
        registration payload, keyed by slot name. A list-valued ``blacklist``
        is the §6.1 suppression vocabulary and is not a slot blacklist."""
        blacklist = data.get("slot_blacklist")
        if blacklist is None and isinstance(data.get("blacklist"), dict):
            blacklist = data["blacklist"]
        if not blacklist:
            return {}
        return {slot.lower(): [str(v) for v in values]
                for slot, values in blacklist.items()}

    def _register(self, lang: str, match_type: str, samples: list,
                  slot_blacklist: dict = None):
        if not samples:
            return
        if slot_blacklist:
            self.slot_blacklists[(lang, match_type)] = slot_blacklist
        if lang not in self.matchers:
            self.matchers[lang] = {}
        if match_type not in self.matchers[lang]:
            self.matchers[lang][match_type] = TemplateMatcher()
        self.matchers[lang][match_type].add_templates(samples)
        LOG.debug(f"Registered {len(samples)} templates for {match_type} ({lang})")

    def handle_register_intent(self, message: Message):
        # legacy padatious topic, match_type is the bare intent_name
        # (padatious matches are looked up by that same name)
        lang, _, intent_name, samples, _ = self._unpack_object(message)
        self._register(lang, intent_name, samples,
                       self._slot_blacklist(message.data))

    def handle_register_template(self, message: Message):
        # OVOS-INTENT-4 §6 spec topic, match_type follows m2v's
        # "skill_id:intent_name" IntentHandlerMatch.match_type convention
        lang, skill_id, intent_name, samples, _ = self._unpack_object(
            message, name_key='intent_name', blacklist_key='blacklist')
        self._register(lang, f"{skill_id}:{intent_name}", samples,
                       self._slot_blacklist(message.data))

    def transform(self, intent: IntentHandlerMatch) -> IntentHandlerMatch:
        """Fill the slots the registered templates extract from the utterance.

        OVOS-TRANSFORM-1 §3.4: "A transformer MAY add entries to
        ``Match.slots``. It SHOULD NOT delete or overwrite slot entries
        produced by the matching engine or by an earlier transformer in the
        chain". A slot the engine already set keeps the engine's value. A
        slot set to None is unresolved and takes the template value.
        """
        sess = intent.updated_session or SessionManager.get()
        matchers = self.matchers.get(sess.lang)
        if matchers:
            if intent.match_type in matchers:
                entities = matchers[intent.match_type].match(intent.utterance)
                LOG.debug(f"{intent.match_type} keyword templates match: {entities}")
                entities = self._drop_blacklisted(
                    entities, sess.lang, intent.match_type)
                for slot, value in entities.items():
                    if intent.match_data.get(slot) is None:
                        intent.match_data[slot] = value
        return intent

    def _drop_blacklisted(self, entities: dict, lang: str,
                          match_type: str) -> dict:
        """OVOS-INTENT-2 §4.3 — a slot the utterance filled with a blacklisted
        value stays unresolved, so the extracted value is discarded instead of
        overwriting what the matching engine deliberately left empty.

        Exclusion is by WHOLE value: a bare anaphoric "it" is dropped, while a
        longer value that merely contains a blacklisted word ("the it crowd")
        is a legitimate binding.
        """
        blacklist = self.slot_blacklists.get((lang, match_type))
        if not blacklist:
            return entities
        kept = {}
        for slot, value in entities.items():
            values = blacklist.get(slot.lower(), [])
            if any(v.lower().split() == str(value).lower().split()
                   for v in values):
                LOG.debug(f"slot {slot!r}={value!r} blacklisted for "
                          f"{match_type} ({lang}); leaving it unresolved")
                continue
            kept[slot] = value
        return kept
