"""Embedding providers for semantic clustering and deduplication."""

from abc import ABC, abstractmethod
import os
from pathlib import Path
from typing import List, Optional
import numpy as np

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from app.core.logging import setup_logger

logger = setup_logger("embeddings")


class EmbeddingProvider(ABC):
    """Abstract base interface for generating text representations and similarity matrices."""

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Generates embedding matrix for a sequence of texts.

        Args:
            texts: List of text strings to embed.

        Returns:
            np.ndarray: 2D array of shape (len(texts), embedding_dimension).
        """
        pass

    def compute_similarity_matrix(self, texts: List[str]) -> np.ndarray:
        """Computes pairwise cosine similarity matrix between all texts.

        Args:
            texts: List of input texts.

        Returns:
            np.ndarray: Symmetric similarity matrix with shape (len(texts), len(texts))
                        and values in [0.0, 1.0].
        """
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        if len(texts) == 1:
            return np.array([[1.0]], dtype=np.float32)

        embeddings = self.embed_texts(texts)
        if embeddings.size == 0:
            return np.eye(len(texts), dtype=np.float32)

        sim_matrix = cosine_similarity(embeddings, embeddings)
        # Numerical stability: clip between 0.0 and 1.0
        np.clip(sim_matrix, 0.0, 1.0, out=sim_matrix)
        # Ensure diagonal is exactly 1.0
        np.fill_diagonal(sim_matrix, 1.0)
        return sim_matrix.astype(np.float32)


class TFIDFEmbeddingProvider(EmbeddingProvider):
    """High-performance lexical-semantic embedding provider using sublinear TF-IDF n-grams.

    Fully offline, deterministic, sub-millisecond execution, and highly effective for
    capturing exact model versions (e.g. 'GPT-4o', 'Claude 3.5 Sonnet', 'o1') and headline phrases.
    """

    def __init__(
        self,
        ngram_range: tuple = (1, 3),
        sublinear_tf: bool = True,
        token_pattern: str = r"(?u)\b[\w\.\-]+\b",
    ):
        """Initializes the TF-IDF vectorizer configuration.

        Args:
            ngram_range: Tuple of (min_n, max_n) n-grams to capture (default 1 to 3).
            sublinear_tf: Apply 1 + log(tf) scaling to suppress high-frequency repetition.
            token_pattern: Regex pattern preserving version numbers, hyphens, and dots.
        """
        self.ngram_range = ngram_range
        self.sublinear_tf = sublinear_tf
        self.token_pattern = token_pattern

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Computes L2-normalized TF-IDF embedding vectors for texts."""
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        # Pre-clean inputs: replace empty or whitespace-only texts with a placeholder
        cleaned_texts = [
            t.strip() if t and t.strip() else "__empty_placeholder__"
            for t in texts
        ]

        vectorizer = TfidfVectorizer(
            ngram_range=self.ngram_range,
            sublinear_tf=self.sublinear_tf,
            token_pattern=self.token_pattern,
            lowercase=True,
            stop_words="english",
            norm="l2",
        )

        try:
            tfidf_matrix = vectorizer.fit_transform(cleaned_texts)
            return tfidf_matrix.toarray().astype(np.float32)
        except ValueError:
            # Occurs if vocabulary is empty (e.g. only stopwords across all texts)
            fallback_vectorizer = TfidfVectorizer(
                token_pattern=self.token_pattern,
                lowercase=True,
                stop_words=None,
                norm="l2",
            )
            try:
                tfidf_matrix = fallback_vectorizer.fit_transform(cleaned_texts)
                return tfidf_matrix.toarray().astype(np.float32)
            except Exception as e:
                logger.warning(f"TF-IDF embedding fallback error: {e}. Returning zeros.")
                return np.zeros((len(texts), 1), dtype=np.float32)


class MiniLMEmbeddingProvider(EmbeddingProvider):
    """Local, offline, CPU-optimized SentenceTransformer provider using quantized ONNX all-MiniLM-L6-v2.

    Runs via onnxruntime and tokenizers with 22MB RAM footprint, requiring no GPU, PyTorch,
    or external network connectivity once downloaded.
    """

    def __init__(self, max_length: int = 128):
        """Initializes ONNX inference session and tokenizer from local cache."""
        self.max_length = max_length
        self._session = None
        self._tokenizer = None
        self._initialized = False
        self._init_error = None
        self._init_runtime()

    def _init_runtime(self) -> None:
        """Attempts to load ONNX runtime and local model checkpoints."""
        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            # Locate local cached snapshot
            cache_base = (
                Path.home()
                / ".cache"
                / "huggingface"
                / "hub"
                / "models--sentence-transformers--all-MiniLM-L6-v2"
                / "snapshots"
            )
            model_path = None
            tok_path = None

            if cache_base.exists():
                for snap_dir in cache_base.iterdir():
                    if snap_dir.is_dir():
                        q_onnx = snap_dir / "onnx" / "model_quint8_avx2.onnx"
                        base_onnx = snap_dir / "onnx" / "model.onnx"
                        t_json = snap_dir / "tokenizer.json"

                        if q_onnx.exists():
                            model_path = q_onnx
                        elif base_onnx.exists():
                            model_path = base_onnx

                        if t_json.exists():
                            tok_path = t_json

                        if model_path and tok_path:
                            break

            if not model_path or not tok_path:
                self._init_error = "Local all-MiniLM-L6-v2 ONNX model or tokenizer not found in cache."
                logger.warning(self._init_error)
                return

            self._tokenizer = Tokenizer.from_file(str(tok_path))
            self._tokenizer.enable_padding(length=self.max_length)
            self._tokenizer.enable_truncation(max_length=self.max_length)

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = min(4, os.cpu_count() or 1)
            self._session = ort.InferenceSession(
                str(model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            self._initialized = True
            logger.info(f"Loaded MiniLMEmbeddingProvider ONNX session from {model_path.name}")
        except Exception as e:
            self._init_error = f"Failed to initialize ONNX runtime: {e}"
            logger.warning(self._init_error)

    @property
    def is_available(self) -> bool:
        """Returns True if local ONNX session and tokenizer are ready."""
        return self._initialized

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        """Computes 384-dimensional dense sentence embeddings using ONNX all-MiniLM-L6-v2."""
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)

        if not self._initialized:
            logger.warning(f"MiniLM ONNX unavailable ({self._init_error}). Falling back to TF-IDF.")
            return TFIDFEmbeddingProvider().embed_texts(texts)

        try:
            cleaned_texts = [
                t.strip() if t and t.strip() else "empty"
                for t in texts
            ]
            encodings = self._tokenizer.encode_batch(cleaned_texts)

            input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
            attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)
            token_type_ids = np.array([e.type_ids for e in encodings], dtype=np.int64)

            outputs = self._session.run(
                None,
                {
                    "input_ids": input_ids,
                    "attention_mask": attention_mask,
                    "token_type_ids": token_type_ids,
                },
            )

            # Mean pooling across token representations using attention mask
            token_embeddings = outputs[0]
            mask_expanded = np.expand_dims(attention_mask, -1).astype(np.float32)
            sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
            mean_pooled = sum_embeddings / sum_mask

            # L2 normalization
            norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
            norms = np.clip(norms, a_min=1e-9, a_max=None)
            normalized = mean_pooled / norms

            return normalized.astype(np.float32)
        except Exception as e:
            logger.warning(f"ONNX inference failure: {e}. Falling back to TF-IDF.")
            return TFIDFEmbeddingProvider().embed_texts(texts)


def get_embedding_provider(provider_type: Optional[str] = None) -> EmbeddingProvider:
    """Factory creating the configured embedding provider.

    Args:
        provider_type: Identifier string ('tfidf', 'minilm', 'sentence_transformers').
                       Defaults to 'tfidf'.

    Returns:
        EmbeddingProvider: Instantiated embedding provider.
    """
    provider_type = (provider_type or "tfidf").lower().strip()
    if provider_type in ("minilm", "sentence_transformers", "onnx"):
        minilm = MiniLMEmbeddingProvider()
        if minilm.is_available:
            return minilm
        logger.warning("MiniLMEmbeddingProvider unavailable, falling back to TFIDFEmbeddingProvider.")
        return TFIDFEmbeddingProvider()
    else:
        return TFIDFEmbeddingProvider()
