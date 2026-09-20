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
import copy
import os.path

from ovos_padatious import fann
from ovos_utils.log import LOG
from ovos_padatious.id_manager import IdManager
from ovos_padatious.util import resolve_conflicts, StrEnum


class Ids(StrEnum):
    unknown_tokens = ':0'
    w_1 = ':1'
    w_2 = ':2'
    w_3 = ':3'
    w_4 = ':4'


class SimpleIntent:
    """General intent used to match sentences or phrases"""
    LENIENCE = 0.6

    def __init__(self, name=''):
        self.name = name
        self.ids = IdManager(Ids)
        self.net = None  # type: fann.neural_net

    def match(self, sent):
        if sent and not self.has_wildcard and not any(token in self.ids for token in sent):
            # No word of the utterance is in this intent's vocabulary and no
            # template of it carries a {slot} that could stand for unknown
            # words, so no template of this intent can produce the utterance.
            # The net has no training row for that shape: the ':null:'
            # pollution rows train to LENIENCE (0.6) on 1-3 unknown tokens,
            # so an all-unknown utterance lands near 0.6 and the exact value
            # depends on the trained weights, which differ across numpy
            # builds. A lone registered intent then claims or drops an
            # unrelated utterance by float noise. Decide it here instead.
            return 0.0
        return max(0, self.net.run(self.vectorize(sent))[0])

    @property
    def has_wildcard(self):
        """True when a training sample carried a ``{slot}`` placeholder: the
        intent can then legitimately match words it never saw."""
        return any(token.startswith('{') for token in self.ids.ids)

    def vectorize(self, sent):
        vector = self.ids.vector()
        unknown = 0
        for token in sent:
            if token in self.ids:
                self.ids.assign(vector, token, 1.0)
            else:
                unknown += 1
        if len(sent) > 0:
            self.ids.assign(vector, Ids.unknown_tokens, unknown / float(len(sent)))
            self.ids.assign(vector, Ids.w_1, len(sent) / 1)
            self.ids.assign(vector, Ids.w_2, len(sent) / 2.)
            self.ids.assign(vector, Ids.w_3, len(sent) / 3.)
            self.ids.assign(vector, Ids.w_4, len(sent) / 4.)
        return vector

    def configure_net(self):
        self.net = fann.neural_net()
        self.net.create_standard_array([len(self.ids), 10, 1])
        self.net.set_activation_function_hidden(fann.SIGMOID_SYMMETRIC_STEPWISE)
        self.net.set_activation_function_output(fann.SIGMOID_SYMMETRIC_STEPWISE)
        self.net.set_train_stop_function(fann.STOPFUNC_BIT)
        self.net.set_bit_fail_limit(0.1)

    def train(self, train_data):
        train_data = copy.copy(train_data)
        for sent in train_data.my_sents(self.name):
            self.ids.add_sent(sent)

        inputs = []
        outputs = []

        n_pos = len(list(train_data.my_sents(self.name)))
        n_neg = len(list(train_data.other_sents(self.name)))

        def add(vec, out):
            inputs.append(self.vectorize(vec))
            outputs.append([out])

        def pollute(sent, p):
            sent = sent[:]
            for _ in range(int((len(sent) + 2) / 3)):
                sent.insert(p, ':null:')
            add(sent, self.LENIENCE)

        def weight(sent):
            def calc_weight(w): return pow(len(w), 3.0)
            total_weight = 0.0
            for word in sent:
                total_weight += calc_weight(word)
            for word in sent:
                weight = 0 if word.startswith('{') else calc_weight(word)
                add([word], weight / total_weight)

        for sent in train_data.my_sents(self.name):
            add(sent, 1.0)
            weight(sent)

            # Generate samples with extra unknown tokens unless
            # the sentence is supposed to allow unknown tokens via the special :0
            if not any(word[0] == ':' and word != ':' for word in sent):
                pollute(sent, 0)
                pollute(sent, len(sent))

        for sent in train_data.other_sents(self.name):
            add(sent, 0.0)
        add([':null:'], 0.0)
        add([], 0.0)

        for sent in train_data.my_sents(self.name):
            without_entities = sent[:]
            for i, token in enumerate(without_entities):
                if token.startswith('{'):
                    without_entities[i] = ':null:'
            if without_entities != sent:
                add(without_entities, 0.0)

        inputs, outputs = resolve_conflicts(inputs, outputs)

        train_data = fann.training_data()
        train_data.set_train_data(inputs, outputs)
        LOG.debug(f"Training {self.name} with {len(self.ids)} inputs and samples: {n_pos} positive + {n_neg} negative")
        # Each attempt re-seeds the net and trains up to 1000 epochs. With
        # libfann one attempt on ~8k rows took about a second, so ten attempts
        # were cheap. The numpy backend takes 20 to 160 s per attempt on a
        # large intent, and a net that does not reach bit_fail 0 on the first
        # attempt does not reach it on the tenth either (weather en-US,
        # T-1645: 49 to 121 failing rows across ten attempts, no trend). Keep
        # the best attempt, and stop as soon as an attempt does not improve on
        # it: the loop used to keep the LAST attempt, which on that run was
        # the worst of the ten.
        best_net, best_fail = None, None
        for _ in range(10):
            self.configure_net()
            self.net.train_on_data(train_data, 1000, 0, 0)
            self.net.test_data(train_data)
            fail = self.net.get_bit_fail()
            if best_fail is None or fail < best_fail:
                best_net, best_fail = self.net, fail
                if fail == 0:
                    break
            else:
                break
        self.net = best_net
        LOG.debug(f"Training {self.name} finished! ({best_fail} of "
                  f"{len(inputs)} samples outside the bit fail limit)")

    def save(self, prefix):
        prefix += '.intent'
        self.net.save(str(prefix + '.net'))  # Must have str()
        self.ids.save(prefix)

    @classmethod
    def from_file(cls, name, prefix):
        prefix += '.intent'
        self = cls(name)
        self.net = fann.neural_net()
        path = str(prefix + '.net')
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        if not self.net.create_from_file(path):
            raise FileNotFoundError(path)
        self.ids.load(prefix)
        return self
