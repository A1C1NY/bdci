"""Label-blind retrieval, frozen local neural reranking and exact reference-token packing."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

from .stale_retrieval import Retriever, tokens
from .stale_packing_v5 import split_sentences
from .storage import digest, read_json, write_json

MODEL_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
MODEL_SHA256 = "c80a8b34256ea453093d612e3ac48d3d965a0c0a48c7906709af8b8e28461bf9"
TOKENIZER_SHA256 = "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"


class LocalReranker:
    def __init__(self, directory, cache, max_length=256, threads=4):
        from tokenizers import Tokenizer
        import onnxruntime as ort
        directory = Path(directory)
        model = directory / "model_quint8_avx2.onnx"
        if digest(model) != MODEL_SHA256:
            raise ValueError("Reranker model hash differs from frozen official LFS object")
        if digest(directory / "tokenizer.json") != TOKENIZER_SHA256:
            raise ValueError("Reference tokenizer hash changed")
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.reader_tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=max_length)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model), options, providers=["CPUExecutionProvider"])
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.identity = {"revision": MODEL_REVISION, "model_sha256": MODEL_SHA256,
                         "tokenizer_sha256": digest(directory / "tokenizer.json"),
                         "max_length": max_length, "threads": threads,
                         "implementation_sha256": digest(__file__), "runtime": ort.__version__}
        self.calls = self.cache_hits = self.pairs = 0
        self.inference_seconds = 0.0

    def count(self, text):
        return len(self.reader_tokenizer.encode(text, add_special_tokens=False).ids)

    def score(self, query, texts):
        payload = {"query": query, "texts": texts, "engine": self.identity}
        signature = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        target = self.cache / (signature + ".json")
        if target.exists():
            saved = read_json(target)
            if (saved["signature"] != signature or len(saved["scores"]) != len(texts)
                    or not all(type(x) in (int, float) and math.isfinite(x) for x in saved["scores"])):
                raise ValueError("Invalid reranker cache")
            self.cache_hits += 1
            return saved["scores"]
        scores = []
        start = time.monotonic()
        for begin in range(0, len(texts), 8):
            encodings = self.tokenizer.encode_batch([(query, text) for text in texts[begin:begin + 8]])
            values = {"input_ids": [e.ids for e in encodings],
                      "attention_mask": [e.attention_mask for e in encodings],
                      "token_type_ids": [e.type_ids for e in encodings]}
            inputs = {item.name: np.asarray(values[item.name], dtype=np.int64) for item in self.session.get_inputs()}
            logits = self.session.run(None, inputs)[0].reshape(-1)
            scores.extend(float(x) for x in logits)
        if len(scores) != len(texts) or not all(math.isfinite(x) for x in scores):
            raise ValueError("Invalid local model scores")
        seconds = time.monotonic() - start
        write_json(target, {"signature": signature, "scores": scores, "seconds": seconds})
        self.calls += 1
        self.pairs += len(texts)
        self.inference_seconds += seconds
        return scores


def bm25_scores(retriever, query):
    scores = []
    for counts, length in zip(retriever.counts, retriever.lengths):
        value = 0.0
        for term in set(tokens(query)):
            tf = counts[term]
            if tf:
                idf = math.log(1 + (len(retriever.docs) - retriever.df[term] + .5) / (retriever.df[term] + .5))
                value += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * length / max(1, retriever.avg)))
        scores.append(value)
    return scores


def query_window(text, query, radius=1):
    """A fixed query-overlap anchor plus neighbors; never sees update annotations."""
    sentences = split_sentences(text)
    if not sentences:
        return text
    query_terms = set(tokens(query))
    # Earliest tie prevents selecting the end of a turn because of label placement.
    anchor = max(range(len(sentences)), key=lambda i: (len(query_terms & set(tokens(sentences[i]))), -i))
    return " ".join(sentences[max(0, anchor - radius):anchor + radius + 1])


def pack(docs, ranking, budget, count, texts=None, *, additive=False):
    if type(budget) is not int or budget < 0:
        raise ValueError("Budget must be a nonnegative integer")
    selected = []
    def serialize(ids):
        return "".join(f"[session {docs[i]['session']}, turn {docs[i]['turn']}] " +
                       (texts[i] if texts is not None else docs[i]["text"]) + "\n" for i in sorted(ids))
    used = 0
    for index in ranking:
        if index in selected:
            continue
        # Safe only for the frozen WordPiece tokenizer: each unit is separated by
        # whitespace and a bracket, so its pre-tokenization cannot merge across units.
        if additive and used + count(serialize([index])) > budget:
            continue
        if count(serialize(selected + [index])) <= budget:
            selected.append(index)
            used = count(serialize(selected))
    context = serialize(selected)
    return {"context": context, "units": count(context), "selected": sorted(selected),
            "sessions": sorted({docs[i]["session"] for i in selected})}


def contexts(view, query, reranker, budgets=(512, 1024, 2048), top_k=32):
    """Only sessions, timestamps, query and uid enter this policy boundary."""
    if set(view) - {"uid", "sessions", "timestamps", "queries"}:
        raise ValueError("Unexpected fields in public retrieval view")
    retriever = Retriever(view)
    scores = bm25_scores(retriever, query)
    ranking = sorted(range(len(scores)), key=lambda i: (scores[i], i), reverse=True)
    candidates = ranking[:top_k]
    neural = reranker.score(query, [retriever.docs[i]["text"] for i in candidates]) if candidates else []
    learned = sorted(zip(candidates, neural), key=lambda pair: (pair[1], pair[0]), reverse=True)
    learned = [i for i, _ in learned]
    windows = {i: query_window(retriever.docs[i]["text"], query) for i in candidates}
    methods = {"bm25_all": (ranking, None), "bm25_32": (candidates, None),
               "ce_32": (learned, None), "bm25_window_32": (candidates, windows),
               "ce_window_32": (learned, windows)}
    results = []
    for budget in budgets:
        for method, (order, text) in methods.items():
            results.append({"method": method, "budget": budget,
                            **pack(retriever.docs, order, budget, reranker.count, text, additive=True)})
    return results, {"candidates": candidates, "candidate_texts": [retriever.docs[i]["text"] for i in candidates],
                     "candidate_windows": [windows[i] for i in candidates], "neural_scores": neural,
                     "candidate_reference_lengths": [reranker.count(retriever.docs[i]["text"]) for i in candidates],
                     "query_reference_length": reranker.count(query)}
