# Copyright 2017 Mycroft AI, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from ovos_utils.log import LOG

from ovos_padatious.util import tokenize, expand_lines, warn_hash_wildcard


class TrainData:
    """
    Training data used to access collections
    of tokenized sentences in intent files
    """

    def __init__(self):
        self.sent_lists = {}

    def copy(self) -> 'TrainData':
        # NOTE: new samples might be added to TrainData object during obj.train(data)
        # which would result in ovos_padatious.training_manager:train:153 - ERROR - Error training XXX: dictionary changed size during iteration
        data = TrainData()
        data.sent_lists = dict(self.sent_lists)
        return data

    def add_lines(self, name, lines):
        warn_hash_wildcard(name, lines)
        lines = expand_lines(lines)
        sents = [tokenize(line) for line in lines if line.strip()]
        if not sents:
            # every line was malformed and skipped by expand_lines: adding
            # an empty entry would register a dead intent/entity that can
            # never match (conf 0.0 forever) instead of surfacing the
            # problem, so refuse it outright and drop any stale entry.
            # OVOS-INTENT-4 §5.3: the rejecting plugin logs at WARN.
            LOG.warning(
                "%r has no valid samples after skipping malformed template "
                "lines - not registering", name,
            )
            self.remove_lines(name)
            return
        self.sent_lists[name] = sents

    def remove_lines(self, name):
        if name in self.sent_lists:
            del self.sent_lists[name]

    def add_file(self, name, file_name):
        with open(file_name, 'r') as f:
            self.add_lines(name, f.readlines())

    def all_sents(self):
        for _, sents in self.sent_lists.items():
            for i in sents:
                yield i

    def my_sents(self, my_name):
        for i in self.sent_lists[my_name]:
            yield i

    def other_sents(self, my_name):
        for name, sents in self.sent_lists.items():
            if name != my_name:
                for i in sents:
                    yield i
