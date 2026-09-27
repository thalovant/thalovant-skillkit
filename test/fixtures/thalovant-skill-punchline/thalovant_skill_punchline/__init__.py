"""Punchline: SkillKit's example of speech markup.

It tells a joke with a pause before the payoff, reads out a code, and orders
a coffee with the French said in French. Each shows one way to add markup:

* `joke` has a `.ssml` twin in English and none in French, so English
  sessions hear the pause and French ones hear the plain line.
* `code` has no twin: the value is marked up, in every language.
* `cheer` has a twin written as a whole `<speak xml:lang>` document.
* `greeting` has neither, and is spoken exactly as OVOS speaks any dialog.
* `order_coffee` builds its sentence in Python.
"""
from thalovant_skillkit.skill import ThalovantFallbackSkill
from thalovant_skillkit.ssml import foreign, pause, say, spell


class PunchlineSkill(ThalovantFallbackSkill):
    FALLBACK_PRIORITY = 97

    def can_answer(self, message) -> bool:
        return self.mentions(self.utterance(message), "JokeKeyword", self.lang_of(message))

    def reply(self, utterance: str, lang: str, context: dict) -> str | None:
        return self.dialog("joke", lang)

    def tell_code(self, code: str) -> None:
        self.speak_dialog("code", {"code": spell(code)})

    def cheer(self) -> None:
        self.speak_dialog("cheer")

    def greet(self, name: str) -> None:
        self.speak_dialog("greeting", {"name": name})

    def order_coffee(self, message):
        return self.speak_to(message, say(
            "One", foreign("café au lait", "fr-FR"), "coming up.", pause("500ms"), "Enjoy.",
        ))
