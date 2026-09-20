import time
from dataclasses import dataclass
from os.path import dirname, join
from threading import Event
from typing import Dict, Optional, List, Union, Any, Tuple

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_plugin_manager.solvers import find_multiple_choice_solver_plugins
from ovos_plugin_manager.templates.pipeline import PipelinePlugin, IntentHandlerMatch
from ovos_spec_tools import voc_match
from ovos_utils import flatten_list
from ovos_utils.events import EventContainer, create_wrapper
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG

# .voc resources shipped with this plugin (locale/<lang>/<name>.voc).
# Matched via ovos-spec-tools voc_match (OVOS-INTENT-2 §4.3 whole-word semantics)
# instead of reaching into ovos-workshop's skill voc_match.
LOCALE_DIR = join(dirname(__file__), "locale")


@dataclass
class Query:
    session_id: str
    query: str
    lang: str
    replies: list = None
    extensions: list = None
    queried_skills: list = None
    query_time: float = 0
    timeout_time: float = 0
    responses_gathered: Event = Event()
    completed: Event = Event()
    answered: bool = False
    selected_skill: str = ""
    callback_data: Optional[Dict[str, Any]] = None

    @property
    def response_confidence(self) -> float:
        return max((k.get("conf", 0) for k in self.replies), default=0.0)


class CommonQAService(PipelinePlugin):
    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        """
        Initialize CommonQAService, configure runtime options, register bus events, and probe for available common-query skills.
         
        Parameters:
            bus (Optional[MessageBusClient | FakeBus]): Optional message bus client to use for inter-component communication.
            config (Optional[Dict]): Optional configuration dictionary; if omitted, configuration is read from the global Configuration under 'intents' -> 'ovos-common-query-pipeline-plugin' (fallback to 'common_query'). Recognized keys include:
                - extension_time: seconds to extend query timeout when a skill reports it is still searching.
                - min_response_wait: minimum time to wait for responses before evaluating.
                - max_response_wait: maximum time to wait for responses (regardless of extensions).
                - min_self_confidence: minimum confidence required for a skill's self-reported score to be considered.
                - min_reranker_score: minimum reranker score required for reranker results to be considered.
                - reranker: plugin name for an optional reranker implementation.
                - ignore_skill_scores: when true and a reranker is available, skill score ordering may be ignored in favor of reranker output.
        
        Side effects:
            - Initializes pipeline plugin state and bus-event tracking.
            - Loads an optional reranker plugin if configured.
            - Registers handlers for 'question:query.response', 'common_query.question', and 'ovos.common_query.pong' bus events.
            - Emits an 'ovos.common_query.ping' message to discover already-loaded common-query skills.
        """
        PipelinePlugin.__init__(self, bus, config)
        self.skill_id = "common_query.openvoiceos"
        # tracks bus handlers so they can be unregistered on shutdown,
        # replacing ovos-workshop's add_event/default_shutdown bookkeeping
        self.events = EventContainer(self.bus)
        self.active_queries: Dict[str, Query] = dict()

        self.common_query_skills = []
        self._deprecated_skills = []

        intent_config = Configuration().get('intents', {})
        config = config or intent_config.get("ovos-common-query-pipeline-plugin") or intent_config.get("common_query") or dict()
        self._extension_time = config.get('extension_time') or 1
        CommonQAService._EXTENSION_TIME = self._extension_time
        self._min_wait = config.get('min_response_wait') or 1
        self._max_time = config.get('max_response_wait') or 4  # regardless of extensions
        self._min_self_confidence = config.get('min_self_confidence', 0.5)
        self._min_reranker_score = config.get('min_reranker_score', 0.2)
        reranker_module = config.get("reranker", "ovos-flashrank-reranker-plugin")
        self.reranker = None
        try:
            for name, plug in find_multiple_choice_solver_plugins().items():
                if name == reranker_module:
                    self.reranker = plug(config=config.get(name, {}))
                    LOG.info(f"CommonQuery ReRanker: {name}")
                    break
            else:
                LOG.info("No CommonQuery ReRanker loaded!")
        except Exception as e:
            LOG.error(f"Failed to load ReRanker plugin: {e}")
        self.ignore_scores = config.get("ignore_skill_scores", True) and self.reranker is not None
        self.add_event('question:query.response', self.handle_query_response)
        self.add_event('common_query.question', self.handle_question)
        self.add_event('ovos.common_query.pong', self.handle_skill_pong)
        self.bus.emit(Message("ovos.common_query.ping"))  # gather any skills that already loaded

    def add_event(self, name: str, handler):
        """
        Register a bus handler, wrapping it for exception-safe execution and
        tracking it for cleanup on shutdown. Mirrors ovos-workshop's add_event
        without depending on the skills framework.
        @param name: Message.msg_type to listen for
        @param handler: callback invoked with the Message
        """
        wrapper = create_wrapper(handler, self.skill_id,
                                 on_start=None, on_end=None,
                                 on_error=lambda e: LOG.exception(
                                     f"error in {name} handler: {e}"))
        self.events.add(name, wrapper)

    def handle_skill_pong(self, message: Message):
        """ track running common query skills """
        if message.data["skill_id"] not in self.common_query_skills:
            self.common_query_skills.append(message.data["skill_id"])
            LOG.debug("Detected CommonQuery skill: " + message.data["skill_id"])
            if message.data.get("is_classic_cq", True):
                deprecated_id = message.data["skill_id"]
                LOG.warning(f"{deprecated_id} is using the deprecated CommonQuery skill class, "
                            f"it might stop working in the near future")
                self._deprecated_skills.append(deprecated_id)

    def is_question_like(self, utterance: str, lang: str) -> bool:
        """
        Check if the input utterance looks like a question for CommonQuery
        @param utterance: user input to evaluate
        @param lang: language of input
        @return: True if input might be a question to handle here
        """
        lang = standardize_lang_tag(lang)
        # skip utterances with less than 3 words
        if len(utterance.split(" ")) < 3:
            LOG.debug("utterance has less than 3 words, doesnt look like a question")
            return False
        # skip utterances meant for common play / weather / other known conflicts
        if voc_match(utterance, "MiscBlacklist", lang, locale=LOCALE_DIR):
            LOG.debug("utterance has 'blacklist' keywords, doesnt look like a general knowledge question")
            return False
        if voc_match(utterance, "Weather", lang, locale=LOCALE_DIR):
            LOG.debug("utterance has 'weather' keywords, doesnt look like a general knowledge question")
            return False
        if voc_match(utterance, "Alerts", lang, locale=LOCALE_DIR):
            LOG.debug("utterance has 'alerts' keywords, doesnt look like a general knowledge question")
            return False
        if voc_match(utterance, "Play", lang, locale=LOCALE_DIR):
            LOG.debug("utterance has 'playback' keywords, doesnt look like a general knowledge question")
            return False
        # require a "question word"
        return voc_match(utterance, "QuestionWord", lang, locale=LOCALE_DIR)

    def match(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Send common query request and select best response

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Language code
            message: Message for session context
        Returns:
            IntentHandlerMatch or None
        """
        lang = standardize_lang_tag(lang)
        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        match = None

        # exit early if no common query skills are installed
        if not self.common_query_skills:
            LOG.info("No CommonQuery skills to search")
            return None
        else:
            LOG.info(f"Gathering answers from skills: {self.common_query_skills}")

        for utterance in utterances:
            LOG.debug(f"is question: {self.is_question_like(utterance, lang)}")
            if self.is_question_like(utterance, lang):
                message.data["lang"] = lang  # only used for speak method
                message.data["utterance"] = utterance
                answered, query = self.handle_question(message,
                                                       emit_dispatch=False)
                if answered and self._meets_min_conf(query):
                    query.callback_data["conf"] = query.response_confidence
                    old_style = query.selected_skill in self._deprecated_skills
                    match = IntentHandlerMatch(match_type='question:action' if old_style else f'question:action.{query.selected_skill}',
                                               match_data=query.callback_data,
                                               skill_id=query.selected_skill,
                                               utterance=utterance)
                break
        return match

    def _meets_min_conf(self, query: Query) -> bool:
        """``min_conf`` floor on a selected answer, shared by ``match()`` and
        the ``common_query.question`` event path so both speak the same
        answers."""
        return query.response_confidence >= self.config.get("min_conf", 0.01)

    def handle_question(self, message: Message,
                        emit_dispatch: bool = True) -> Tuple[bool, Query]:
        """
        Send the phrase to CommonQuerySkills and prepare for handling replies.

        @param emit_dispatch: emit the winning skill's ``question:action``
            dispatch from ``_query_timeout``. The ``common_query.question``
            bus event path needs this (a bus handler's return value is
            discarded); the ``match()`` pipeline stage sets it False because
            it completes through its returned IntentHandlerMatch instead,
            and a second emit would make the winning skill speak twice.
        """
        utt = message.data.get('utterance')
        sess = SessionManager.get(message)
        query = Query(session_id=sess.session_id, query=utt, lang=sess.lang,
                      replies=[], extensions=[],
                      query_time=time.time(),
                      timeout_time=time.time() + self._max_time,
                      responses_gathered=Event(), completed=Event(),
                      answered=False,
                      # ovos-bus-client>=2.4 may carry None for omitted session
                      # collections (OVOS-SESSION-1 omission rule); guard before
                      # iterating or membership-testing them.
                      queried_skills=[s for s in (sess.blacklisted_skills or [])
                                      if s in self.common_query_skills])  # dont wait for these
        assert query.responses_gathered.is_set() is False
        assert query.completed.is_set() is False
        self.active_queries[sess.session_id] = query
        self.bus.emit(message.forward("enclosure.mouth.think"))

        LOG.info(f"Searching for '{utt}' with max search time: {self._max_time}s")
        # Send the query to anyone listening for them
        msg = message.reply('question:query', data={'phrase': utt})
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        # Define the timeout_msg here before any responses modify context
        timeout_msg = msg.response(msg.data)
        self.bus.emit(msg)

        # OVOS-COMMON-QUERY-1 §7.2: the ceiling is the absolute bound, whatever
        # a late extension wrote to timeout_time
        ceiling = query.query_time + self._max_time
        while not query.responses_gathered.wait(0.1):
            # forcefully timeout if search is still going
            if time.time() > min(query.timeout_time, ceiling):
                if not query.completed.is_set():
                    LOG.debug(f"Session Timeout gathering responses ({query.session_id})")
                    LOG.warning(f"Timed out getting responses for: {query.query}")
                break

        self._query_timeout(timeout_msg, emit_dispatch=emit_dispatch)
        if not query.completed.wait(5):
            raise TimeoutError("Timed out processing responses")
        answered = bool(query.answered)
        self.active_queries.pop(sess.session_id)
        LOG.debug(f"answered={answered}|"
                  f"remaining active_queries={len(self.active_queries)}")
        return answered, query

    def handle_query_response(self, message: Message):
        search_phrase = message.data['phrase']
        skill_id = message.data['skill_id']
        searching = message.data.get('searching')
        answer = message.data.get('answer')

        sess = SessionManager.get(message)
        if skill_id in (sess.blacklisted_skills or []):
            LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
            return

        sess_id = SessionManager.get(message).session_id
        query = self.active_queries.get(sess_id)
        if not query:
            LOG.warning(f"Late answer received from {skill_id}, no active query for: {search_phrase}")
            return

        # Manage requests for time to complete searches
        if searching:
            LOG.debug(f"{skill_id} is searching")
            # request extending the timeout by EXTENSION_TIME. OVOS-COMMON-QUERY-1
            # §7.2: a searching skill is still outstanding, so an extension
            # never moves the deadline earlier, and never past the hard ceiling
            query.timeout_time = min(max(query.timeout_time,
                                         time.time() + self._extension_time),
                                     query.query_time + self._max_time)
            # TODO: Perhaps block multiple extensions?
            if skill_id not in query.extensions:
                query.extensions.append(skill_id)
        else:
            # Search complete, don't wait on this skill any longer
            if answer:
                LOG.info(f'Answer from {skill_id}')
                query.replies.append(message.data)
                if skill_id not in query.queried_skills:
                    query.queried_skills.append(skill_id)

            # Remove the skill from list of timeout extensions
            if skill_id in query.extensions:
                LOG.debug(f"Done waiting for {skill_id}")
                query.extensions.remove(skill_id)

            # if all skills answered, stop searching
            if self.common_query_skills and set(query.queried_skills) == set(self.common_query_skills):
                LOG.debug("All skills answered")
                query.responses_gathered.set()

    def _query_timeout(self, message: Message, emit_dispatch: bool = True):
        """
        All accepted responses have been provided, either because all skills
        replied or a timeout condition was met. The best response is selected,
        and `question:action` is emitted so the associated skill's
        handler can perform any additional actions.
        @param message: question:query.response Message with `phrase` data
        @param emit_dispatch: emit the winning skill's dispatch. Needed on the
            common_query.question bus event path (a bus handler's return value
            is discarded); match() completes through its returned
            IntentHandlerMatch instead and passes False here.
        """
        sess = SessionManager.get(message)
        query = self.active_queries.get(SessionManager.get(message).session_id)
        LOG.info(f'Check responses with {len(query.replies)} replies')
        search_phrase = message.data.get('phrase', "")
        if query.extensions:
            query.extensions = []
        self.bus.emit(message.forward("enclosure.mouth.reset"))

        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []
        for response in query.replies:
            if response['conf'] < self._min_self_confidence:
                LOG.debug(f"Discarding {response['skill_id']} low confidence answer: {response['conf']} - {response['answer']}")
                continue
            if response["skill_id"] in (sess.blacklisted_skills or []):
                continue
            if not self.ignore_scores:
                if not best or response['conf'] > best['conf']:
                    best = response
                    ties = [response]
                elif response['conf'] == best['conf']:
                    ties.append(response)
            else:
                best = response
                # let's rerank all answers and ignore skill self-reported confidence
                ties.append(response)

        if best:
            tied_ids = set(m["skill_id"] for m in ties)
            if len(tied_ids) > 1:
                LOG.debug(f"Tied skills: {tied_ids}")
            answers = {m["answer"]: m for m in ties}
            if self.reranker is None:
                if len(tied_ids) > 1:
                    LOG.debug("No ReRanker available, selecting randomly")
                # semi-random pick, no re-ranker available
                # ASSUMPTION: if skill took longer to process query, answer is more accurate
                best_ans = list(answers.keys())[-1]
                best = answers[best_ans]
            else:
                reranked = self.reranker.rerank(query.query,
                                                list(answers.keys()),
                                                lang=query.lang)
                if self._min_reranker_score is None:
                    # by default not set, the optimal value is reranker plugin specific
                    candidates = reranked
                else:
                    candidates = [ans for ans in reranked if ans[0] >= self._min_reranker_score]
                    for score, ans in [r for r in reranked if r not in candidates]:
                        LOG.debug(f"ReRanker discarded low confidence answer: {score} - {answers[ans]}")

                for score, ans in candidates:
                    LOG.info(f"ReRanker score: {score} - {answers[ans]}")

                if candidates:
                    best_ans = candidates[0][1]
                    best = answers[best_ans]
                else:
                    best = None

            if best is not None:
                LOG.info('Handling with: ' + str(best['skill_id']))
                query.selected_skill = best["skill_id"]
                query.callback_data = {**best, "phrase": search_phrase}
                query.answered = True
                # A bus event handler's return value is discarded, so when
                # handle_question is reached via the common_query.question
                # event (the match_type a pipeline plugin's special-label map
                # dispatches), nobody consumes this contest's result unless
                # the winning skill's dispatch is emitted here. match()
                # reaches the same selection through its return value and
                # sets emit_dispatch=False, so both paths complete without
                # double-dispatching.
                # The same floor match() applies before it builds its return
                # value: the two paths must speak the same answers.
                if emit_dispatch and self._meets_min_conf(query):
                    old_style = query.selected_skill in self._deprecated_skills
                    match_type = ('question:action' if old_style
                                  else f'question:action.{query.selected_skill}')
                    self.bus.emit(message.reply(
                        match_type,
                        data={**query.callback_data,
                              "conf": query.response_confidence},
                        context={"skill_id": query.selected_skill}))
            else:
                LOG.debug("No good answers from skills, not answering question")
                query.answered = False
        else:
            query.answered = False
        query.completed.set()

    def shutdown(self):
        self.events.clear()  # remove events registered via self.add_event
