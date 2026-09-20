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
"""Pure numpy replacement for the subset of the FANN API used by padatious.

Implements fully connected feed-forward networks trained with batch iRPROP-
(FANN's default training algorithm) and reads/writes the FANN_FLO_2.1 text
format, so models trained with libfann keep loading and models saved here
remain loadable by libfann.
"""
import os
import zlib
from functools import lru_cache
from typing import List, Optional

import numpy as np

# FANN activation function enum values (fann_activationfunc_enum)
SIGMOID = 3
SIGMOID_STEPWISE = 4
SIGMOID_SYMMETRIC = 5
SIGMOID_SYMMETRIC_STEPWISE = 6

# FANN stop function enum values (fann_stopfunc_enum)
STOPFUNC_MSE = 0
STOPFUNC_BIT = 1

_SYMMETRIC = (SIGMOID_SYMMETRIC, SIGMOID_SYMMETRIC_STEPWISE)

# iRPROP- hyperparameters (FANN defaults)
_RPROP_DELTA_ZERO = 0.1
_RPROP_DELTA_MIN = 0.0
_RPROP_DELTA_MAX = 50.0
_RPROP_INCREASE = 1.2
_RPROP_DECREASE = 0.5

_HEADER = "FANN_FLO_2.1"


# y-values of the 6 interpolation points FANN uses for its STEPWISE
# piecewise-linear sigmoid approximations (fann_update_stepwise)
_STEPWISE_RESULTS = np.array([0.005, 0.05, 0.25, 0.75, 0.95, 0.995])


@lru_cache(maxsize=None)
def _stepwise_points(steepness: float, symmetric: bool):
    if symmetric:
        ys = 2.0 * _STEPWISE_RESULTS - 1.0
        return np.arctanh(ys) / steepness, ys, -1.0, 1.0
    ys = _STEPWISE_RESULTS
    return np.log(ys / (1.0 - ys)) / (2.0 * steepness), ys, 0.0, 1.0


def _stepwise(x: np.ndarray, steepness: float, symmetric: bool) -> np.ndarray:
    xs, ys, lo, hi = _stepwise_points(steepness, symmetric)
    return np.interp(x, xs, ys, left=lo, right=hi)


def _activate(x: np.ndarray, func: int, steepness: float) -> np.ndarray:
    if func == SIGMOID_SYMMETRIC_STEPWISE:
        return _stepwise(x, steepness, symmetric=True)
    if func == SIGMOID_STEPWISE:
        return _stepwise(x, steepness, symmetric=False)
    if func in _SYMMETRIC:
        return np.tanh(steepness * x)
    return 1.0 / (1.0 + np.exp(-2.0 * steepness * x))


def _activate_deriv(y: np.ndarray, func: int, steepness: float) -> np.ndarray:
    # derivative expressed in terms of the activation output y; FANN clips y
    # away from the saturation points so gradients never fully die
    if func in _SYMMETRIC:
        y = np.clip(y, -0.98, 0.98)
        return steepness * (1.0 - y * y)
    y = np.clip(y, 0.01, 0.99)
    return 2.0 * steepness * y * (1.0 - y)


def _error_transform(err: np.ndarray, func: int) -> np.ndarray:
    """FANN's error post-processing: halve for symmetric activations, then
    apply the TANH error function (its default) which amplifies large errors."""
    if func in _SYMMETRIC:
        err = err / 2.0
    clipped = np.clip(err, -0.9999999, 0.9999999)
    return np.where(np.abs(err) > 0.9999999, np.sign(err) * 17.0,
                    np.log((1.0 + clipped) / (1.0 - clipped)))


class training_data:
    """Drop-in for fann.training_data: holds input/target arrays."""

    def __init__(self):
        self.inputs: Optional[np.ndarray] = None
        self.outputs: Optional[np.ndarray] = None
        self.seed = 0
        # counts trainings against this data, so a caller retrying with a
        # fresh net explores a different initialization
        self.attempt = 0

    def set_train_data(self, inputs, outputs) -> None:
        self.inputs = np.asarray(inputs, dtype=np.float64)
        self.outputs = np.asarray(outputs, dtype=np.float64)
        if self.inputs.ndim != 2 or self.outputs.ndim != 2 or \
                len(self.inputs) != len(self.outputs):
            raise ValueError("inputs and outputs must be equal-length 2D data")
        self.seed = zlib.crc32(self.outputs.tobytes(),
                               zlib.crc32(self.inputs.tobytes()))
        self.attempt = 0


class neural_net:
    """Drop-in for fann.neural_net covering the API padatious uses."""

    def __init__(self):
        self.layers = []  # type: List[int]
        self.weights = []  # type: List[np.ndarray]  # (n_in + 1, n_out) incl. bias row
        self.hidden_activation = SIGMOID_SYMMETRIC_STEPWISE
        self.output_activation = SIGMOID_SYMMETRIC_STEPWISE
        self.steepness = 0.5
        self.stop_function = STOPFUNC_BIT
        self.bit_fail_limit = 0.35  # FANN default
        self.bit_fail = 0
        self._seed_from_data = False

    # --- configuration -------------------------------------------------

    def create_standard_array(self, layers: List[int]) -> None:
        self.layers = list(layers)
        # placeholder weights; train_on_data reseeds from the training data
        # itself so identical data always yields identical models (libfann
        # seeded from the clock, making trained models irreproducible)
        self._init_weights(np.random.default_rng(0))
        self._seed_from_data = True

    def _init_weights(self, rng) -> None:
        self.weights = [
            rng.uniform(-0.1, 0.1, size=(n_in + 1, n_out))
            for n_in, n_out in zip(self.layers[:-1], self.layers[1:])
        ]

    def set_activation_function_hidden(self, func: int) -> None:
        self.hidden_activation = func

    def set_activation_function_output(self, func: int) -> None:
        self.output_activation = func

    def set_train_stop_function(self, func: int) -> None:
        self.stop_function = func

    def set_bit_fail_limit(self, limit: float) -> None:
        self.bit_fail_limit = limit

    # --- inference -----------------------------------------------------

    def _forward(self, x: np.ndarray) -> List[np.ndarray]:
        """Returns activations per layer; x is (n_samples, n_inputs)."""
        activations = [x]
        last = len(self.weights) - 1
        for i, w in enumerate(self.weights):
            func = self.output_activation if i == last else self.hidden_activation
            # w rows are (inputs..., bias)
            z = activations[-1] @ w[:-1] + w[-1]
            activations.append(_activate(z, func, self.steepness))
        return activations

    def run(self, input_vector) -> List[float]:
        x = np.asarray(input_vector, dtype=np.float64)
        last = len(self.weights) - 1
        for i, w in enumerate(self.weights):
            func = self.output_activation if i == last else self.hidden_activation
            x = _activate(x @ w[:-1] + w[-1], func, self.steepness)
        return x.tolist()

    # --- training ------------------------------------------------------

    def _count_bit_fail(self, predicted: np.ndarray, target: np.ndarray) -> int:
        return int(np.sum(np.abs(predicted - target) > self.bit_fail_limit))

    def train_on_data(self, data: training_data, max_epochs: int,
                      epochs_between_reports: int, desired_error: float) -> None:
        x, y = data.inputs, data.outputs
        if self._seed_from_data:
            self._seed_from_data = False
            self._init_weights(np.random.default_rng(
                [data.seed, data.attempt] + self.layers))
            data.attempt += 1
        grads_prev = [np.zeros_like(w) for w in self.weights]
        deltas = [np.full_like(w, _RPROP_DELTA_ZERO) for w in self.weights]
        n = len(x)

        for _ in range(max_epochs):
            activations = self._forward(x)
            out = activations[-1]
            err = out - y

            if self.stop_function == STOPFUNC_BIT:
                if self._count_bit_fail(out, y) == 0:
                    break
            elif np.mean(err ** 2) <= desired_error:
                break

            # backprop gradients, with FANN's error transform and
            # saturation-clipped derivatives
            grads = []
            delta = _error_transform(err, self.output_activation) * \
                _activate_deriv(out, self.output_activation, self.steepness) / n
            for i in range(len(self.weights) - 1, -1, -1):
                grads.append(np.vstack([activations[i].T @ delta,
                                        delta.sum(axis=0, keepdims=True)]))
                if i > 0:
                    delta = (delta @ self.weights[i][:-1].T) * _activate_deriv(
                        activations[i], self.hidden_activation, self.steepness)
            grads.reverse()

            # iRPROP- weight update, replicating FANN's
            # fann_update_weights_irpropm exactly: slope is the negative
            # gradient; a zero sign-product counts as "same sign" (step still
            # grows); on a sign flip the slope is zeroed BEFORE the direction
            # test, so the weight moves +step that epoch; weights clip at 1500
            for w, g, s_prev, d in zip(self.weights, grads, grads_prev, deltas):
                slope = -g
                same_sign = slope * s_prev
                np.maximum(d, 0.0001, out=d)
                flipped = same_sign < 0
                np.multiply(d, _RPROP_INCREASE, out=d, where=~flipped)
                np.multiply(d, _RPROP_DECREASE, out=d, where=flipped)
                np.clip(d, _RPROP_DELTA_MIN, _RPROP_DELTA_MAX, out=d)
                slope[flipped] = 0.0
                w += np.where(slope < 0, -d, d)
                np.clip(w, -1500.0, 1500.0, out=w)
                s_prev[...] = slope

    def test_data(self, data: training_data) -> None:
        out = self._forward(data.inputs)[-1]
        self.bit_fail = self._count_bit_fail(out, data.outputs)

    def get_bit_fail(self) -> int:
        return self.bit_fail

    # --- FANN_FLO_2.1 persistence ---------------------------------------

    def save(self, path: str) -> None:
        # libfann's loader requires every header field, in this exact order
        lines = [_HEADER,
                 f"num_layers={len(self.layers)}",
                 "learning_rate=0.700000",
                 "connection_rate=1.000000",
                 "network_type=0",
                 "learning_momentum=0.000000",
                 "training_algorithm=2",
                 "train_error_function=1",
                 f"train_stop_function={self.stop_function}",
                 "cascade_output_change_fraction=0.010000",
                 "quickprop_decay=-0.000100",
                 "quickprop_mu=1.750000",
                 f"rprop_increase_factor={_RPROP_INCREASE:.6f}",
                 f"rprop_decrease_factor={_RPROP_DECREASE:.6f}",
                 f"rprop_delta_min={_RPROP_DELTA_MIN:.6f}",
                 f"rprop_delta_max={_RPROP_DELTA_MAX:.6f}",
                 f"rprop_delta_zero={_RPROP_DELTA_ZERO:.6f}",
                 "adam_beta1=0.900000",
                 "adam_beta2=0.999000",
                 "adam_epsilon=0.00000001",
                 "cascade_output_stagnation_epochs=12",
                 "cascade_candidate_change_fraction=0.010000",
                 "cascade_candidate_stagnation_epochs=12",
                 "cascade_max_out_epochs=150",
                 "cascade_min_out_epochs=50",
                 "cascade_max_cand_epochs=150",
                 "cascade_min_cand_epochs=50",
                 "cascade_num_candidate_groups=2",
                 f"bit_fail_limit={self.bit_fail_limit:.20e}",
                 "cascade_candidate_limit=1.00000000000000000000e+03",
                 "cascade_weight_multiplier=4.00000000000000022204e-01",
                 "cascade_activation_functions_count=10",
                 "cascade_activation_functions=3 5 7 8 10 11 14 15 16 17 ",
                 "cascade_activation_steepnesses_count=4",
                 "cascade_activation_steepnesses=2.50000000000000000000e-01 "
                 "5.00000000000000000000e-01 7.50000000000000000000e-01 "
                 "1.00000000000000000000e+00 ",
                 "layer_sizes=" + " ".join(str(s + 1) for s in self.layers) + " ",
                 "scale_included=0"]

        neurons = []
        connections = []
        last = len(self.layers) - 1
        for layer_idx, size in enumerate(self.layers):
            if layer_idx == 0:
                neurons.extend(["(0, 0, 0.00000000000000000000e+00)"] * (size + 1))
                continue
            func = self.output_activation if layer_idx == last \
                else self.hidden_activation
            n_inputs = self.layers[layer_idx - 1] + 1
            w = self.weights[layer_idx - 1]
            # global index of the first neuron in the previous layer
            offset = sum(s + 1 for s in self.layers[:layer_idx - 1])
            for j in range(size):
                neurons.append(f"({n_inputs}, {func}, {self.steepness:.20e})")
                # weight rows are (inputs..., bias); bias is the last neuron
                # of the previous layer, matching FANN's global numbering
                for k in range(n_inputs):
                    connections.append(f"({offset + k}, {w[k, j]:.20e})")
            neurons.append(f"(0, {func}, 0.00000000000000000000e+00)")

        lines.append("neurons (num_inputs, activation_function, "
                     "activation_steepness)=" + " ".join(neurons) + " ")
        lines.append("connections (connected_to_neuron, weight)=" +
                     " ".join(connections) + " ")
        with open(path, 'w') as f:
            f.write("\n".join(lines) + "\n")

    def create_from_file(self, path: str) -> bool:
        if not os.path.isfile(path):
            return False
        with open(path) as f:
            content = f.read()
        if not content.startswith("FANN"):
            return False

        fields = {}
        for line in content.splitlines()[1:]:
            if '=' in line:
                key, _, value = line.partition('=')
                fields[key.strip()] = value.strip()

        sizes = [int(v) for v in fields["layer_sizes"].split()]
        self.layers = [s - 1 for s in sizes]  # strip bias neurons
        self.stop_function = int(fields.get("train_stop_function",
                                            STOPFUNC_BIT))
        self.bit_fail_limit = float(fields.get("bit_fail_limit", 0.35))

        neurons = _parse_tuples(fields[
            "neurons (num_inputs, activation_function, activation_steepness)"])
        conns = _parse_tuples(fields["connections (connected_to_neuron, weight)"])

        # per-layer activation/steepness from the first real neuron of the layer
        pos = sizes[0]
        for layer_idx in range(1, len(sizes)):
            func, steepness = int(neurons[pos][1]), float(neurons[pos][2])
            self.steepness = steepness
            if layer_idx == len(sizes) - 1:
                self.output_activation = func
            else:
                self.hidden_activation = func
            pos += sizes[layer_idx]

        self.weights = []
        ci = 0
        for n_in, n_out in zip(self.layers[:-1], self.layers[1:]):
            w = np.empty((n_in + 1, n_out))
            for j in range(n_out):
                for k in range(n_in + 1):
                    w[k, j] = float(conns[ci][1])
                    ci += 1
            self.weights.append(w)
        return True


def _parse_tuples(text: str) -> List[List[str]]:
    return [part.split(", ") for part in
            text.replace("(", "").split(")") if part.strip()]
