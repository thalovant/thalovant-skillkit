"""CLDR plural rules, evaluated for a count.

A language file carries its plural categories as the rules Unicode CLDR
publishes for it, verbatim (UTS #35, "Language Plural Rules")::

    plural:
      one: "i = 1 and v = 0"
      few: "v = 0 and i % 10 = 2..4 and i % 100 != 12..14"
      many: "v = 0 and i % 10 = 0 or v = 0 and i % 10 = 5..9 or ..."

"other" is never written: it is what remains. The rule syntax is small --
operands, ``%``, ``=`` / ``!=`` against values and ranges, ``and``, ``or`` --
and this module evaluates it for integer counts, where ``v``, ``f``, ``t``,
``w``, ``e`` and ``c`` are all zero. The legacy spellings ``mod``, ``is``,
``in``, ``within`` and ``not`` are read too. Everything after ``@integer``
or ``@decimal`` is a sample, not a rule, and is ignored.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Callable, Mapping

#: CLDR's order of categories; the first rule that holds names the form.
CATEGORIES = ("zero", "one", "two", "few", "many")

_TOKEN = re.compile(r"\s*(\d+\.\.\d+|\d+|!=|=|%|,|[a-z]+)")
_OPERANDS = ("n", "i", "v", "f", "t", "w", "e", "c")


class PluralRuleError(ValueError):
    """A rule this module cannot read; the message shows where."""


def _tokens(rule: str) -> list[str]:
    text = rule.split("@", 1)[0].strip()
    out: list[str] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise PluralRuleError(f"cannot read {rule!r} at {text[pos:pos + 12]!r}")
        out.append(m.group(1))
        pos = m.end()
    return out


def _operand(name: str, n: int) -> int:
    # For an integer count every fraction operand is zero; the absolute
    # value and the integer digits are the count itself.
    if name in ("n", "i"):
        return abs(n)
    if name in ("v", "f", "t", "w", "e", "c"):
        return 0
    raise PluralRuleError(f"{name!r} is not a plural operand")


class _Parser:
    def __init__(self, rule: str) -> None:
        self.rule = rule
        self.tokens = _tokens(rule)
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise PluralRuleError(f"cannot read {self.rule!r}: expected {expected or 'more'} "
                                  f"at token {self.pos}")
        self.pos += 1
        return token

    def condition(self) -> Callable[[int], bool]:
        branches = [self.and_condition()]
        while self.peek() == "or":
            self.take("or")
            branches.append(self.and_condition())
        return lambda n: any(branch(n) for branch in branches)

    def and_condition(self) -> Callable[[int], bool]:
        relations = [self.relation()]
        while self.peek() == "and":
            self.take("and")
            relations.append(self.relation())
        return lambda n: all(relation(n) for relation in relations)

    def number(self) -> int:
        token = self.take()
        if not token.isdigit():
            raise PluralRuleError(f"cannot read {self.rule!r}: expected a number, got {token!r}")
        return int(token)

    def relation(self) -> Callable[[int], bool]:
        operand = self.take()
        if operand not in _OPERANDS:
            raise PluralRuleError(f"cannot read {self.rule!r}: {operand!r} is not a plural operand")
        modulus: int | None = None
        if self.peek() in ("%", "mod"):
            self.take()
            modulus = self.number()
        negate = False
        op = self.take()
        if op == "not":
            negate = True
            op = self.take()
        if op == "is":
            if self.peek() == "not":  # the legacy spelling "n mod 10 is not 11"
                self.take("not")
                negate = True
            value = self.number()
            ranges = [(value, value)]
        elif op in ("=", "!=", "in", "within"):
            negate = negate or op == "!="
            ranges = self.range_list()
        else:
            raise PluralRuleError(f"cannot read {self.rule!r}: {op!r} is not a relation")

        def holds(n: int) -> bool:
            value = _operand(operand, n)
            if modulus is not None:
                value %= modulus
            inside = any(low <= value <= high for low, high in ranges)
            return not inside if negate else inside

        return holds

    def range_list(self) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        while True:
            token = self.take()
            if ".." in token:
                low, high = token.split("..")
                ranges.append((int(low), int(high)))
            elif token.isdigit():
                ranges.append((int(token), int(token)))
            else:
                raise PluralRuleError(f"cannot read {self.rule!r}: expected a value, got {token!r}")
            if self.peek() != ",":
                return ranges
            self.take(",")


@lru_cache(maxsize=512)
def parse(rule: str) -> Callable[[int], bool]:
    """The rule as a predicate over an integer count. An empty rule always holds."""
    if not rule.strip() or rule.strip().startswith("@"):
        return lambda n: True
    parser = _Parser(rule)
    predicate = parser.condition()
    if parser.peek() is not None:
        raise PluralRuleError(f"cannot read {rule!r}: trailing {parser.peek()!r}")
    return predicate


def category(rules: Mapping[str, str] | None, n: int) -> str:
    """Which plural form a count takes under the language's rules, in CLDR's
    order of categories, and "other" when no rule holds. An empty table is
    CLDR saying every count is "other" (Japanese); no table at all is a
    language nothing describes, and gets the least surprising guess: one
    form for one and one for the rest."""
    if rules is None:
        return "one" if n == 1 else "other"
    for name in CATEGORIES:
        rule = rules.get(name)
        if rule is not None and parse(str(rule))(int(n)):
            return name
    return "other"
