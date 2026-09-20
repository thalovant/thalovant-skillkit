import random
from os.path import dirname, isfile
from typing import Optional

from ovos_plugin_manager.templates.solvers import QuestionSolver


class FailureSolver(QuestionSolver):
    enable_tx = False
    priority = 9999

    def __init__(self, config=None):
        config = config or {}
        super().__init__(config)


    def get_spoken_answer(self, query: str,
                          lang: Optional[str] = None,
                          units: Optional[str] = None) -> Optional[str]:
        """
        Obtain the spoken answer for a given query.

        Args:
            query (str): The query text.
            lang (Optional[str]): Optional language code. Defaults to None.
            units (Optional[str]): Optional units for the query. Defaults to None.

        Returns:
            str: The spoken answer as a text response.
        """
        lines = ["404"]  # all langs
        if lang:
            path = f"{dirname(__file__)}/locale/{lang.lower()}/no_brain.dialog"
            if isfile(path):
                with open(path) as f:
                    lines = [l for l in f.read().split("\n")
                             if l.strip() and not l.startswith("#")]
        return random.choice(lines)


if __name__ == "__main__":
    bot = FailureSolver()
    print(bot.spoken_answer("hello!", lang="en-US"))
    print(bot.spoken_answer("Olá", lang="pt-pt"))
