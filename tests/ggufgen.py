"""GGUF BF16 propio y diminuto para probar cuantización; no es un modelo útil para inferencia."""
import math
import struct
from pathlib import Path


def _string(value):
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _value(kind, value):
    if kind == 8:
        return _string(value)
    if kind == 9:
        subtype, values = value
        return struct.pack("<IQ", subtype, len(values)) + b"".join(_value(subtype, v) for v in values)
    return struct.pack("<" + {4: "I", 6: "f"}[kind], value)


def build_bf16(path):
    metadata = [("general.architecture", 8, "llama"), ("general.name", 8, "eolfi-sintetico-no-inferencia"),
                ("general.file_type", 4, 32), ("llama.block_count", 4, 1),
                ("llama.context_length", 4, 128), ("llama.embedding_length", 4, 256),
                ("llama.feed_forward_length", 4, 256), ("llama.attention.head_count", 4, 8),
                ("llama.attention.head_count_kv", 4, 8), ("llama.rope.dimension_count", 4, 32),
                ("llama.attention.layer_norm_rms_epsilon", 6, 1e-5),
                ("tokenizer.ggml.model", 8, "llama"),
                ("tokenizer.ggml.tokens", 9, (8, ["<s>", "</s>", "<unk>", *[f"tok{i}" for i in range(29)]])),
                ("tokenizer.ggml.scores", 9, (6, [0.0] * 32)),
                ("tokenizer.ggml.token_type", 9, (4, [1] * 32)),
                ("tokenizer.ggml.bos_token_id", 4, 0), ("tokenizer.ggml.eos_token_id", 4, 1),
                ("tokenizer.ggml.unknown_token_id", 4, 2)]
    weights = b"".join(struct.pack("<f", math.sin(i * 0.17) * 0.25)[2:] for i in range(256 * 32))
    norm = struct.pack("<256f", *([1.0] * 256))
    tensors = [("token_embd.weight", [256, 32], 30, weights), ("blk.0.attn_norm.weight", [256], 0, norm)]
    for name in ("attn_q", "attn_k", "attn_v", "attn_output", "ffn_gate", "ffn_up", "ffn_down"):
        tensors.append((f"blk.0.{name}.weight", [256, 256], 30, weights * 8))
    tensors.extend([("blk.0.ffn_norm.weight", [256], 0, norm), ("output_norm.weight", [256], 0, norm),
                    ("output.weight", [256, 32], 30, weights)])
    header = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(metadata))
    for key, kind, value in metadata:
        header += _string(key) + struct.pack("<I", kind) + _value(kind, value)
    payload = b""
    for name, dims, kind, data in tensors:
        payload += b"\0" * (-len(payload) % 32)
        header += _string(name) + struct.pack("<I", len(dims))
        header += b"".join(struct.pack("<Q", d) for d in dims) + struct.pack("<IQ", kind, len(payload))
        payload += data
    Path(path).write_bytes(header + b"\0" * (-len(header) % 32) + payload)
    return [struct.unpack("<f", b"\0\0" + weights[i:i + 2])[0] for i in range(0, len(weights), 2)]
