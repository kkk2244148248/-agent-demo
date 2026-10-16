"""本地 BGE-M3：dense + sparse（对齐 eduagent）。"""
from __future__ import annotations

import os
from typing import Optional

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)


class BGEMEmbedder:
    _instance: Optional["BGEMEmbedder"] = None

    def __init__(self, model_path: str):
        import torch
        from FlagEmbedding import BGEM3FlagModel

        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"BGE-M3 路径不存在: {model_path}")

        logger.info(f"bge_m3.loading path={model_path}")
        use_fp16 = torch.cuda.is_available()
        self._model = BGEM3FlagModel(model_name_or_path=model_path, use_fp16=use_fp16)
        logger.info(f"bge_m3.loaded use_fp16={use_fp16}")

    @classmethod
    def get_instance(cls) -> "BGEMEmbedder":
        if cls._instance is None:
            path = get_settings().bge_m3_model_path
            cls._instance = BGEMEmbedder(path)
        return cls._instance

    @classmethod
    def is_ready(cls) -> bool:
        return cls._instance is not None

    def encode(
        self,
        texts: list[str],
        batch_size: int = 8,
    ) -> tuple[list[list[float]], list[dict]]:
        output = self._model.encode(
            texts,
            batch_size=batch_size,
            max_length=8192,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense = output["dense_vecs"].tolist()
        # numpy.float16 → float，避免序列化问题
        sparse = [
            {int(k): float(v) for k, v in d.items()}
            for d in output["lexical_weights"]
        ]
        return dense, sparse

    def encode_query(self, text: str) -> tuple[list[float], dict]:
        dense_list, sparse_list = self.encode([text], batch_size=1)
        return dense_list[0], sparse_list[0]
