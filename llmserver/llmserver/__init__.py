"""llmserver 包."""

import os

os.environ.setdefault("CFLAGS", "-Wno-macro-redefined")
os.environ.setdefault("CXXFLAGS", "-Wno-macro-redefined")
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD","spawn")
os.environ.setdefault("VLLM_USE_V2_MODEL_RUNNER","0")

__version__ = "0.1.0"
