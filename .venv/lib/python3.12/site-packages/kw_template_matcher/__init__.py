import itertools
import re
import warnings
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple

from simplematch import match as sm


class TemplateMatcher:
    """
    Matches text to predefined templates using slot filling and exact structural matching.
    """

    def __init__(self):
        self.templates: Dict[str, List[str]] = defaultdict(list)

    def add_templates(self, templates: List[str]) -> None:
        """
        Adds templates for matching, extracting slots from templates.

        Args:
            templates (List[str]): A list of templates with slots.
        """
        for template in templates:
            expanded = expand_template(template)
            for t in expanded:
                slots = re.findall(r"\{(\w+)\}", t)
                if not slots:
                    continue
                key = "|".join(sorted(slots))
                if t not in self.templates[key]:
                    self.templates[key].append(t)

    def match(self, query: str, threshold: Optional[float] = None) -> Dict[str, str]:
        """Return the slots of the best template match, or ``{}``.

        Args:
            query (str): The input query.
            threshold: deprecated and ignored. See ``predict``.
        """
        preds = [m[1] for m in self.predict(query, threshold)]
        if preds:
            return preds[0]
        return {}

    def predict(self, query: str, threshold: Optional[float] = None) -> List[Tuple[float, Dict[str, str]]]:
        """Return every template match as ``(score, slots)``, best first.

        Every match `simplematch` returns is structurally exact: each literal
        token of the template is in the query. The score is the share of the
        query's tokens the template pins down as literals, in [0, 1]. When several
        templates match, the one with more literal tokens ranks first, even
        if that puts a shared leading article on the wrong side of the
        split: with `'play {query}'` and `'play the {thing}'` registered,
        `"play the beatles"` returns `{"thing": "beatles"}` first, not
        `{"query": "the beatles"}`.

        `threshold` is deprecated and ignored. It used to compare the
        template literal against the whole utterance and dropped correct
        matches whenever the slot value was long. Passing it raises a
        DeprecationWarning.

        Args:
            query (str): The input query.

        Returns:
            List[Tuple[float, Dict[str, str]]]: (score, slots) pairs, sorted by
            score, highest first.
        """
        if threshold is not None:
            warnings.warn("TemplateMatcher.predict/match: 'threshold' is "
                          "deprecated and ignored; every match is structurally "
                          "exact", DeprecationWarning, stacklevel=2)
        query_tokens = max(1, len(query.split()))

        def match_template(ent_templates: Tuple[str, List[str]]) -> List[Tuple[float, Dict[str, str]]]:
            ent, templates = ent_templates
            result = []
            for t in templates:
                m = sm(t, query)
                if m:
                    # `sm` only returns a hit for a structurally exact match (every literal
                    # token in the template is present in the query), so this is never a
                    # fuzzy/approximate match and must not be discarded by `threshold`, which
                    # was comparing the raw template literal (e.g. "play {query}") against the
                    # whole utterance and dropping correct extractions whenever the slot value
                    # was long relative to the template. When several templates match the same
                    # query, rank them by the count of literal (non-slot) tokens they
                    # contain: the template that pins down more of the utterance in literal
                    # words is the more specific/confident match.
                    tokens = t.split()
                    literal_tokens = sum(1 for tok in tokens if not re.fullmatch(r"\{\w+\}", tok))
                    result.append((min(1.0, literal_tokens / query_tokens), m))
            return result

        with ThreadPoolExecutor() as executor:
            results = executor.map(match_template, self.templates.items())

        matches = [item for sublist in results for item in sublist]
        if matches:
            matches.sort(key=lambda k: k[0], reverse=True)
        return matches


def expand_template(template: str) -> list[str]:
    def expand_optional(text):
        """Replace [optional] with two options: one with and one without."""
        return re.sub(r"\[([^\[\]]+)\]", lambda m: f"({m.group(1)}|)", text)

    def expand_alternatives(text):
        """Expand (alternative|choices) into a list of choices."""
        parts = []
        for segment in re.split(r"(\([^\(\)]+\))", text):
            if segment.startswith("(") and segment.endswith(")"):
                options = segment[1:-1].split("|")
                parts.append(options)
            else:
                parts.append([segment])
        return itertools.product(*parts)

    def fully_expand(texts):
        """Iteratively expand alternatives until all possibilities are covered."""
        result = set(texts)
        while True:
            expanded = set()
            for text in result:
                options = list(expand_alternatives(text))
                expanded.update(["".join(option).strip() for option in options])
            if expanded == result:  # No new expansions found
                break
            result = expanded
        return sorted(result)  # Return a sorted list for consistency

    # Expand optional items first
    template = expand_optional(template)

    # Fully expand all combinations of alternatives
    return fully_expand([template])


def expand_slots(template: str, slots: dict[str, list[str]]) -> list[str]:
    """Expand a template by first expanding alternatives and optional components,
    then substituting slot placeholders with their corresponding options.

    Args:
        template (str): The input string template to expand.
        slots (dict): A dictionary where keys are slot names and values are lists of possible replacements.

    Returns:
        list[str]: A list of all expanded combinations.
    """
    # Expand alternatives and optional components
    base_expansions = expand_template(template)

    # Process slots
    all_sentences = []
    for sentence in base_expansions:
        matches = re.findall(r"\{([^\{\}]+)\}", sentence)
        if matches:
            # Create all combinations for slots in the sentence
            slot_options = [slots.get(match, [f"{{{match}}}"]) for match in matches]
            for combination in itertools.product(*slot_options):
                filled_sentence = sentence
                for slot, replacement in zip(matches, combination):
                    filled_sentence = filled_sentence.replace(f"{{{slot}}}", replacement)
                all_sentences.append(filled_sentence)
        else:
            # No slots to expand
            all_sentences.append(sentence)

    return all_sentences


if __name__ == "__main__":
    matcher = TemplateMatcher()
    matcher.add_templates([
        "[hello, ](call me|my name is) {name} [and] [I am from {location}]",
    ])

    query = "my name is Alice and I am from The United Kingdom"
    results = matcher.predict(query)

    for score, match in results:
        print(score, match)
        # 0.5918367346938775 {'name': 'Alice', 'location': 'The United Kingdom'}

    template = "change [the ]brightness to {brightness_level} and color to {color_name}"
    slots = {
        "brightness_level": ["low", "medium", "high"],
        "color_name": ["red", "green", "blue"]
    }

    expanded_sentences = expand_slots(template, slots)
    for sentence in expanded_sentences:
        print(sentence)
        # change the brightness to low and color to red
        # change the brightness to low and color to green
        # change the brightness to low and color to blue
        # change the brightness to medium and color to red
        # change the brightness to medium and color to green
        # change the brightness to medium and color to blue
        # change the brightness to high and color to red
        # change the brightness to high and color to green
        # change the brightness to high and color to blue
        # change brightness to low and color to red
        # change brightness to low and color to green
        # change brightness to low and color to blue
        # change brightness to medium and color to red
        # change brightness to medium and color to green
        # change brightness to medium and color to blue
        # change brightness to high and color to red
        # change brightness to high and color to green
        # change brightness to high and color to blue

    templates = [
        "[hello,] (call me|my name is) {name}",
        "Expand (alternative|choices) into a list of choices.",
        "sentences have [optional] words ",
        "alternative words can be (used|written)",
        "sentence[s] can have (pre|suf)fixes mid word too",
        "do( the | )thing(s|) (old|with) style and( no | )spaces",
        "[(this|that) is optional]",
        "tell me a [{joke_type}] joke",
        "play {query} [in ({device_name}|{skill_name}|{zone_name})]"
    ]
    for template in templates:
        print("###", template)
        expanded_sentences = expand_template(template)
        for sentence in expanded_sentences:
            print("-", sentence)
        # ### [hello,] (call me|my name is) {name}
        # - call me {name}
        # - hello, call me {name}
        # - hello, my name is {name}
        # - my name is {name}
        # ### Expand (alternative|choices) into a list of choices.
        # - Expand alternative into a list of choices.
        # - Expand choices into a list of choices.
        # ### sentences have [optional] words
        # - sentences have  words
        # - sentences have optional words
        # ### alternative words can be (used|written)
        # - alternative words can be used
        # - alternative words can be written
        # ### sentence[s] can have (pre|suf)fixes mid word too
        # - sentence can have prefixes mid word too
        # - sentence can have suffixes mid word too
        # - sentences can have prefixes mid word too
        # - sentences can have suffixes mid word too
        # ### do( the | )thing(s|) (old|with) style and( no | )spaces
        # - do the thing old style and no spaces
        # - do the thing old style and spaces
        # - do the thing with style and no spaces
        # - do the thing with style and spaces
        # - do the things old style and no spaces
        # - do the things old style and spaces
        # - do the things with style and no spaces
        # - do the things with style and spaces
        # - do thing old style and no spaces
        # - do thing old style and spaces
        # - do thing with style and no spaces
        # - do thing with style and spaces
        # - do things old style and no spaces
        # - do things old style and spaces
        # - do things with style and no spaces
        # - do things with style and spaces
        # ### [(this|that) is optional]
        # -
        # - that is optional
        # - this is optional
        # ### tell me a [{joke_type}] joke
        # - tell me a  joke
        # - tell me a {joke_type} joke
        # ### play {query} [in ({device_name}|{skill_name}|{zone_name})]
        # - play {query}
        # - play {query} in {device_name}
        # - play {query} in {skill_name}
        # - play {query} in {zone_name}
