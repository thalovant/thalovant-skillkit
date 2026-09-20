import json
import os.path
import re
from typing import Optional

from langcodes import tag_distance
from ovos_plugin_manager.templates.agents import YesNoEngine
from ovos_utils.lang import standardize_lang_tag
from quebra_frases import word_tokenize


class HeuristicYesNoEngine(YesNoEngine):
    """
    Engine for evaluating answers to yes/no questions.

    Determines if a user input means "yes", "no" or undefined
    """
    def __init__(self, config=None):
        super().__init__(config)
        locale = f"{os.path.dirname(__file__)}/locale"
        self.resources = {}
        for lang in os.listdir(locale):
            fname = f"{locale}/{lang}/yesno.json"
            if os.path.isfile(fname):
                with open(fname, encoding="utf-8") as f:
                    lang = standardize_lang_tag(lang)
                    self.resources[lang] = json.load(f)

    @staticmethod
    def normalize(text: str, lang: str):
        # Remove single characters surrounded by spaces
        text = re.sub(r'\s+[a-zA-Z]\s+', ' ', text)
        # Replace multiple spaces with a single space
        text = re.sub(r'\s+', ' ', text).strip()
        # Convert to lowercase
        text = text.lower()

        # Handle language-specific normalization
        if lang.startswith("en"):
            text = text.replace("don't", "do not")

        return " ".join(word_tokenize(text))

    def _match_lang(self, lang: str) -> str:
        """Find the best matching language in self.resources.

        Args:
            lang: Language tag to match

        Returns:
            Best matching language tag or None if no close match found
        """
        lang = standardize_lang_tag(lang)
        if lang not in self.resources:
            best_lang = None
            best_dist = 100000
            for candidate in self.resources.keys():
                dist = tag_distance(lang, candidate)
                if dist < best_dist:
                    best_lang = candidate
                    best_dist = dist
            if best_dist > 10:
                raise ValueError(f"Unsupported language: {lang!r}. Available: {list(self.resources.keys())}")
            lang = best_lang
        return lang

    def yes_or_no(self, question: str, response: str, lang: Optional[str] = None) -> Optional[bool]:
        """Evaluate whether a response means yes, no, or is neutral.

        Args:
            question: The yes/no question asked (used for context)
            response: The user's response text to classify
            lang: Language code (e.g., "en-us", "pt-pt"). Defaults to "en-us".

        Returns:
            True if response indicates yes, False if no, None if neutral/unclear
        """
        lang = lang or "en-US"
        lang = self._match_lang(lang)
        text = self.normalize(response, lang)

        # if user says yes but later says no, he changed his mind mid-sentence
        # the highest index is the last yesno word
        res = None
        best = -1

        # Compile regex patterns, guarding against empty lists
        yes_pattern = re.compile(r'\b(?:' + '|'.join(self.resources[lang]["yes"]) + r')\b')
        no_pattern = re.compile(r'\b(?:' + '|'.join(self.resources[lang]["no"]) + r')\b')
        neutral_yes_words = self.resources[lang].get("neutral_yes", [])
        neutral_no_words = self.resources[lang].get("neutral_no", [])
        neutral_yes_pattern = re.compile(r'\b(?:' + '|'.join(neutral_yes_words) + r')\b') if neutral_yes_words else None
        neutral_no_pattern = re.compile(r'\b(?:' + '|'.join(neutral_no_words) + r')\b') if neutral_no_words else None

        # Match yes words
        for match in yes_pattern.finditer(text):
            idx = match.start()
            if idx >= best:
                best = idx
                res = True

        # Match no words
        for match in no_pattern.finditer(text):
            idx = match.start()
            if idx >= best:
                best = idx

                # Handle double negatives (e.g., "not a lie", "not lying")
                # Use a proximity pattern: no-word followed by neutral_no within
                # 5 tokens, allowing connective words between them.
                no_word = re.escape(match.group())
                double_neg = False
                for neutral in self.resources[lang].get("neutral_no", []):
                    pattern = rf"\b{no_word}\b(?:\s+\S+){{0,1}}\s+\b{re.escape(neutral)}\b"
                    if re.search(pattern, text):
                        double_neg = True
                        break
                if double_neg:
                    res = True
                else:
                    res = False

        # Match neutral no (if no "yes" detected before)
        if res is None and neutral_no_pattern:
            for match in neutral_no_pattern.finditer(text):
                idx = match.start()
                if idx >= best:
                    best = idx
                    res = False

        # Match neutral yes (if no "no" detected before)
        if res is None and neutral_yes_pattern:
            for match in neutral_yes_pattern.finditer(text):
                idx = match.start()
                if idx >= best:
                    best = idx
                    res = True

        # None - neutral
        # True - yes
        # False - no
        return res


if __name__ == "__main__":
    cfg = {}
    bot = HeuristicYesNoEngine(config=cfg)
    print(bot.yes_or_no("The sun is blue", "disagree", lang="en-AU"))
