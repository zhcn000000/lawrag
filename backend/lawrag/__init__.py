import sys

# for compatibility with httpx
import httpx2  # ruff:ignore[unused-import]

sys.modules["httpx"] = sys.modules["httpx2"]
for name, module in list(sys.modules.items()):
    if name.startswith("httpx2.") and module is not None:
        sys.modules.setdefault("httpx." + name.removeprefix("httpx2."), module)
