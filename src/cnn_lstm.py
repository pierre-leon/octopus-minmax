"""A small 1D CNN-LSTM that maps several past days onto the next 48 half-hours.

Each day is convolved along its half-hours so a short appliance spike becomes
a local feature. Mean and max pooling keep both the day's level and its peaks.
An LSTM then reads those day vectors in order, and a dense layer emits 48 slots.
"""

from __future__ import annotations

from typing import Dict

import numpy as np


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -40, 40)))


class CnnLstm:
    def __init__(self, n_channels: int, n_slots: int = 48, hidden: int = 16,
                 conv_channels: int = 8, kernel: int = 3, seed: int = 0):
        if kernel % 2 == 0:
            raise ValueError("kernel must be odd so the convolution keeps every slot")
        self.n_channels = n_channels
        self.n_slots = n_slots
        self.hidden = hidden
        self.conv_channels = conv_channels
        self.kernel = kernel
        rng = np.random.default_rng(seed)
        conv_scale = math_sqrt(2.0 / (kernel * n_channels))
        self.params = {
            "conv_w": rng.normal(0, conv_scale, (kernel, n_channels, conv_channels)),
            "conv_b": np.zeros(conv_channels),
            "lstm_wx": rng.normal(0, math_sqrt(1.0 / (2 * conv_channels)), (2 * conv_channels, 4 * hidden)),
            "lstm_wh": rng.normal(0, math_sqrt(1.0 / hidden), (hidden, 4 * hidden)),
            "lstm_b": np.zeros(4 * hidden),
            "dense_w": rng.normal(0, math_sqrt(1.0 / hidden), (hidden, n_slots)),
            "dense_b": np.zeros(n_slots),
        }
        # Start with the forget gate open so the first epochs can carry a day forward.
        self.params["lstm_b"][hidden:2 * hidden] = 1.0
        self._adam_t = 0
        self._adam_m = {name: np.zeros_like(value) for name, value in self.params.items()}
        self._adam_v = {name: np.zeros_like(value) for name, value in self.params.items()}

    def predict(self, sequences: np.ndarray) -> np.ndarray:
        predicted, _cache = self._forward(sequences)
        return predicted

    def train(self, sequences: np.ndarray, targets: np.ndarray, weights: np.ndarray,
              epochs: int, lr: float = 1e-3, batch_size: int = 32) -> float:
        if len(sequences) == 0 or epochs <= 0:
            return 0.0
        last = 0.0
        order = np.arange(len(sequences))
        for _epoch in range(epochs):
            np.random.default_rng(self._adam_t + 1).shuffle(order)
            for start in range(0, len(order), batch_size):
                batch = order[start:start + batch_size]
                last = self._train_batch(
                    sequences[batch], targets[batch], weights[batch], lr,
                )
                if not np.isfinite(last):
                    return last
        return last

    def save(self, path: str) -> None:
        np.savez(path, **self.params)

    def load(self, path: str) -> None:
        with np.load(path) as payload:
            for name in self.params:
                self.params[name] = payload[name]

    def _train_batch(self, sequences: np.ndarray, targets: np.ndarray,
                     weights: np.ndarray, lr: float) -> float:
        predicted, cache = self._forward(sequences)
        loss, grad = _output_loss(predicted, targets, weights)
        grads = self._backward(cache, grad)
        _clip(grads, 1.0)
        self._adam(grads, lr)
        return loss

    def _forward(self, sequences: np.ndarray):
        # sequences: (batch, days, slots, channels)
        batch, days, slots, channels = sequences.shape
        flat = sequences.reshape(batch * days, slots, channels)
        conv, conv_cache = _conv_relu(flat, self.params["conv_w"], self.params["conv_b"])
        pooled, pool_cache = _mean_max_pool(conv)
        day_vectors = pooled.reshape(batch, days, -1)
        hidden, lstm_cache = _lstm(
            day_vectors, self.params["lstm_wx"], self.params["lstm_wh"], self.params["lstm_b"],
        )
        predicted = hidden @ self.params["dense_w"] + self.params["dense_b"]
        cache = {
            "shape": (batch, days, slots, channels),
            "conv": conv_cache,
            "pool": pool_cache,
            "lstm": lstm_cache,
            "hidden": hidden,
        }
        return predicted, cache

    def _backward(self, cache: dict, grad_output: np.ndarray) -> Dict[str, np.ndarray]:
        hidden = cache["hidden"]
        grads = {
            "dense_w": hidden.T @ grad_output,
            "dense_b": grad_output.sum(axis=0),
        }
        grad_hidden = grad_output @ self.params["dense_w"].T
        grad_days, grads["lstm_wx"], grads["lstm_wh"], grads["lstm_b"] = _lstm_backward(
            cache["lstm"], grad_hidden, self.params["lstm_wx"], self.params["lstm_wh"],
        )
        batch, days, _slots, _channels = cache["shape"]
        grad_pooled = grad_days.reshape(batch * days, -1)
        grad_conv = _mean_max_backward(cache["pool"], grad_pooled)
        grads["conv_w"], grads["conv_b"], _grad_input = _conv_relu_backward(
            cache["conv"], grad_conv, self.params["conv_w"],
        )
        return grads

    def _adam(self, grads: Dict[str, np.ndarray], lr: float) -> None:
        self._adam_t += 1
        for name, grad in grads.items():
            moment = 0.9 * self._adam_m[name] + 0.1 * grad
            velocity = 0.999 * self._adam_v[name] + 0.001 * (grad * grad)
            self._adam_m[name] = moment
            self._adam_v[name] = velocity
            moment_hat = moment / (1 - 0.9 ** self._adam_t)
            velocity_hat = velocity / (1 - 0.999 ** self._adam_t)
            self.params[name] -= lr * moment_hat / (np.sqrt(velocity_hat) + 1e-8)


def _output_loss(predicted: np.ndarray, targets: np.ndarray, weights: np.ndarray):
    valid = np.isfinite(targets)
    diff = np.zeros_like(predicted)
    diff[valid] = predicted[valid] - targets[valid]
    counts = np.maximum(valid.sum(axis=1), 1)
    per_sample = (diff ** 2).sum(axis=1) / counts
    weight = weights / max(float(weights.sum()), 1e-8)
    loss = float(np.sum(weight * per_sample))
    grad = (2.0 * diff / counts[:, None]) * weight[:, None]
    grad[~valid] = 0.0
    return loss, grad


def _conv_relu(values: np.ndarray, weight: np.ndarray, bias: np.ndarray):
    batch, length, _channels = values.shape
    kernel = weight.shape[0]
    pad = kernel // 2
    padded = np.pad(values, ((0, 0), (pad, pad), (0, 0)))
    columns = np.stack([padded[:, offset:offset + length, :] for offset in range(kernel)], axis=2)
    linear = np.einsum("btkc,kco->bto", columns, weight) + bias
    activated = np.maximum(linear, 0)
    return activated, {"columns": columns, "mask": linear > 0, "pad": pad, "length": length}


def _conv_relu_backward(cache: dict, grad_output: np.ndarray, weight: np.ndarray):
    grad_linear = grad_output * cache["mask"]
    grad_w = np.einsum("btkc,bto->kco", cache["columns"], grad_linear)
    grad_b = grad_linear.sum(axis=(0, 1))
    grad_columns = np.einsum("bto,kco->btkc", grad_linear, weight)
    kernel = weight.shape[0]
    pad = cache["pad"]
    length = cache["length"]
    grad_padded = np.zeros((grad_output.shape[0], length + 2 * pad, weight.shape[1]))
    for offset in range(kernel):
        grad_padded[:, offset:offset + length, :] += grad_columns[:, :, offset, :]
    grad_input = grad_padded[:, pad:pad + length, :]
    return grad_w, grad_b, grad_input


def _mean_max_pool(values: np.ndarray):
    length = values.shape[1]
    mean = values.mean(axis=1)
    max_index = np.argmax(values, axis=1)
    maximum = np.take_along_axis(values, max_index[:, None, :], axis=1)[:, 0, :]
    return np.concatenate([mean, maximum], axis=1), {
        "length": length,
        "max_index": max_index,
        "channels": values.shape[2],
    }


def _mean_max_backward(cache: dict, grad_pooled: np.ndarray) -> np.ndarray:
    length = cache["length"]
    channels = cache["channels"]
    grad_mean = grad_pooled[:, :channels]
    grad_max = grad_pooled[:, channels:]
    grad = np.repeat(grad_mean[:, None, :] / length, length, axis=1)
    batch = np.arange(grad.shape[0])[:, None]
    channel = np.arange(channels)[None, :]
    np.add.at(grad, (batch, cache["max_index"], channel), grad_max)
    return grad


def _lstm(sequence: np.ndarray, weight_x: np.ndarray, weight_h: np.ndarray, bias: np.ndarray):
    batch, steps, _features = sequence.shape
    hidden = weight_h.shape[0]
    state_h = np.zeros((batch, hidden))
    state_c = np.zeros((batch, hidden))
    cache = []
    for step in range(steps):
        incoming = sequence[:, step, :]
        gates = incoming @ weight_x + state_h @ weight_h + bias
        input_g, forget_g, cell_g, output_g = np.split(gates, 4, axis=1)
        input_g = _sigmoid(input_g)
        forget_g = _sigmoid(forget_g)
        output_g = _sigmoid(output_g)
        cell_g = np.tanh(cell_g)
        previous_h, previous_c = state_h, state_c
        state_c = forget_g * previous_c + input_g * cell_g
        tanh_c = np.tanh(state_c)
        state_h = output_g * tanh_c
        cache.append((incoming, previous_h, previous_c, input_g, forget_g, cell_g, output_g, tanh_c))
    return state_h, cache


def _lstm_backward(cache: list, grad_h: np.ndarray, weight_x: np.ndarray, weight_h: np.ndarray):
    hidden = weight_h.shape[0]
    grad_c = np.zeros_like(grad_h)
    grad_wx = np.zeros_like(weight_x)
    grad_wh = np.zeros_like(weight_h)
    grad_b = np.zeros(4 * hidden)
    grad_steps = []
    for incoming, previous_h, previous_c, input_g, forget_g, cell_g, output_g, tanh_c in reversed(cache):
        grad_o = grad_h * tanh_c
        grad_tanh = grad_h * output_g
        grad_c = grad_c + grad_tanh * (1 - tanh_c ** 2)
        grad_i = grad_c * cell_g
        grad_g = grad_c * input_g
        grad_f = grad_c * previous_c
        grad_c_prev = grad_c * forget_g
        grad_i_z = grad_i * input_g * (1 - input_g)
        grad_f_z = grad_f * forget_g * (1 - forget_g)
        grad_g_z = grad_g * (1 - cell_g ** 2)
        grad_o_z = grad_o * output_g * (1 - output_g)
        grad_z = np.concatenate([grad_i_z, grad_f_z, grad_g_z, grad_o_z], axis=1)
        grad_wx += incoming.T @ grad_z
        grad_wh += previous_h.T @ grad_z
        grad_b += grad_z.sum(axis=0)
        grad_steps.append(grad_z @ weight_x.T)
        grad_h = grad_z @ weight_h.T
        grad_c = grad_c_prev
    grad_input = np.stack(grad_steps[::-1], axis=1)
    return grad_input, grad_wx, grad_wh, grad_b


def _clip(grads: Dict[str, np.ndarray], max_norm: float) -> None:
    total = 0.0
    for grad in grads.values():
        total += float(np.sum(grad * grad))
    norm = math_sqrt(total)
    if norm > max_norm:
        scale = max_norm / (norm + 1e-8)
        for name in grads:
            grads[name] *= scale


def math_sqrt(value: float) -> float:
    return float(np.sqrt(value))
