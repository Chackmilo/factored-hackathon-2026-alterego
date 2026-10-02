"""E5 over the policy corpus (roadmap Task 2.3): intfloat/multilingual-e5-small in int8 ONNX, the learned side of
Hypothesis 5 against BM25.

Offline for now: E5 does not fit Vercel's 500 MB bundle with today's code (Task 2.0, docs/SUPABASE_VERCEL.md 6.3), so
onnxruntime and tokenizers are dev dependencies, imported only when the real embedder is built, and the API never
reaches this module (src/rag/__init__.py leaves it out; tests/test_runtime_dependencies.py). The benchmark of Task 4.1
measures it with --e5. Serving it (embeddings precomputed in the build, loaded on the first policy question) waits for
the bundle to fit and for the decision of Task 4.2.

    uv run python -m src.rag.onnx_retriever download   # the pinned files into models/e5-small/ (git-ignored)
"""
from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path
from typing import Protocol

import numpy as np

from src.rag.bm25_retriever import Hit
from src.rag.corpus import PolicyCorpus

MODEL_REPO = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"  # the commit measured in Task 2.0
MODEL_FILES = {  # local name -> (path in the model repo, SHA-256)
    "model_qint8_avx512_vnni.onnx": ("onnx/model_qint8_avx512_vnni.onnx", "dd476dd0c2514e9b9be83aeb3853fac0763e0bdf4a71645407587d77c48a2d88"),
    "tokenizer.json": ("onnx/tokenizer.json", "0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39"),
}
DEFAULT_MODEL_DIR = Path("models/e5-small")


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def verify_model(model_dir: Path) -> None:
    """Every model file present with its pinned SHA-256, so a partial or different download never loads."""
    for name, (_, expected) in MODEL_FILES.items():
        path = Path(model_dir) / name
        if not path.is_file():
            raise FileNotFoundError(f"{path} is missing: uv run python -m src.rag.onnx_retriever download")
        if _sha256(path) != expected:
            raise ValueError(f"{path} does not match the SHA-256 pinned for {MODEL_REPO} at {MODEL_REVISION}")


def download_model(model_dir: Path = DEFAULT_MODEL_DIR) -> None:
    """Fetches the pinned revision's files; a file is kept only when its SHA-256 matches."""
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    for name, (remote, expected) in MODEL_FILES.items():
        target = model_dir / name
        if target.is_file() and _sha256(target) == expected:
            continue
        partial = target.with_name(target.name + ".part")
        urllib.request.urlretrieve(f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{remote}", partial)
        if _sha256(partial) != expected:
            partial.unlink()
            raise ValueError(f"{remote} at {MODEL_REVISION} does not match its pinned SHA-256")
        partial.replace(target)


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Average of the token vectors the attention mask keeps, L2-normalized: the model card's average_pool."""
    pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
    return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class OnnxE5Embedder:
    """The int8 model on one CPU thread, as on the 1 vCPU of a Hobby function."""

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR):
        verify_model(model_dir)
        import onnxruntime as ort  # dev dependencies while E5 stays offline (Task 2.0)
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1
        self._session = ort.InferenceSession(str(Path(model_dir) / "model_qint8_avx512_vnni.onnx"), options,
                                             providers=["CPUExecutionProvider"])
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(Path(model_dir) / "tokenizer.json"))
        self._tokenizer.enable_truncation(max_length=512)

    def embed(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            encoding = self._tokenizer.encode(text)
            ids = np.array([encoding.ids], dtype=np.int64)
            mask = np.array([encoding.attention_mask], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self._inputs:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self._session.run(["last_hidden_state"], feeds)[0]
            vectors.append(mean_pool(hidden, mask)[0])
        return np.vstack(vectors)


class E5Retriever:
    """BM25Retriever's interface over E5: cosine similarity between the question and each clause, best first."""

    name = "e5"

    def __init__(self, corpus: PolicyCorpus, embedder: Embedder):
        self._clause_ids = [c.clause_id for c in corpus.clauses]
        self._embedder = embedder
        self._passages = embedder.embed([f"passage: {c.index_text}" for c in corpus.clauses])  # the text BM25 indexes

    def search(self, text: str, k: int = 3) -> list[Hit]:
        """The k best clauses, best first; the vectors are unit length, so the dot product is the cosine."""
        scores = self._passages @ self._embedder.embed([f"query: {text}"])[0]
        best = sorted(range(len(self._clause_ids)), key=lambda i: scores[i], reverse=True)[:k]
        return [Hit(self._clause_ids[i], float(scores[i])) for i in best]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=f"Download {MODEL_REPO} (int8 ONNX) at the pinned revision.")
    parser.add_argument("command", choices=["download"])
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    args = parser.parse_args(argv)
    download_model(Path(args.model_dir))
    print(f"{MODEL_REPO} at {MODEL_REVISION} in {args.model_dir}: SHA-256 verified")


if __name__ == "__main__":
    main()
