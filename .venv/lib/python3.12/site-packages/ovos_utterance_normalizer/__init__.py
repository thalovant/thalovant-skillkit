import string
from typing import Optional, List

import ftfy
from ovos_plugin_manager.templates.transformers import UtteranceTransformer

from ovos_utterance_normalizer.normalizer import Normalizer, CatalanNormalizer, CzechNormalizer, \
    PortugueseNormalizer, AzerbaijaniNormalizer, RussianNormalizer, EnglishNormalizer, UkrainianNormalizer, \
    GermanNormalizer


class UtteranceNormalizerPlugin(UtteranceTransformer):
    """plugin to normalize utterances by normalizing numbers, punctuation and contractions
    language specific pre-processing is handled here too
    this helps intent parsers"""

    def __init__(self, name="ovos-utterance-normalizer", priority=1):
        super().__init__(name, priority)

    @staticmethod
    def get_normalizer(lang: str):
        if lang.startswith("en"):
            return EnglishNormalizer()
        elif lang.startswith("pt"):
            return PortugueseNormalizer()
        elif lang.startswith("uk"):
            return UkrainianNormalizer()
        elif lang.startswith("ca"):
            return CatalanNormalizer()
        elif lang.startswith("cz"):
            return CzechNormalizer()
        elif lang.startswith("az"):
            return AzerbaijaniNormalizer()
        elif lang.startswith("ru"):
            return RussianNormalizer()
        elif lang.startswith("de"):
            return GermanNormalizer()
        return Normalizer()

    @staticmethod
    def strip_punctuation(utterance: str):
        return utterance.strip(string.punctuation).strip()

    def transform(self, utterances: List[str],
                  context: Optional[dict] = None) -> (list, dict):
        context = context or {}
        lang = context.get("lang") or self.config.get("lang", "en-us")
        normalizer = self.get_normalizer(lang)

        norm = []
        # 1 - expand contractions
        # 2 - original utterance
        # 3 - normalized utterance
        fix_unicode = self.config.get("fix_encoding_errors", True)
        for u in utterances:
            if fix_unicode:
                u = ftfy.fix_text(u)
            norm.append(normalizer.expand_contractions(u))
            norm.append(u)
            norm.append(normalizer.normalize(u))

        if self.config.get("strip_punctuation", True):
            norm = [self.strip_punctuation(u) for u in norm]

        # this deduplicates the list while keeping order
        return list(dict.fromkeys(norm)), context
