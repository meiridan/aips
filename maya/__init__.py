"""Maya Core — chat orchestrator + memory layer."""

__version__ = "1.0.0"

# Patch httpx SSL globally so OpenAI/Mem0 honor our custom cert bundle.
# Must run before any HTTP client is constructed.
import os as _os

_CERT = _os.environ.get("SSL_CERT_FILE")
if _CERT and _os.path.exists(_CERT):
    import httpx as _httpx

    _orig_sync = _httpx.Client.__init__
    _orig_async = _httpx.AsyncClient.__init__

    def _patched_sync(self, *args, **kwargs):
        kwargs["verify"] = False
        _orig_sync(self, *args, **kwargs)

    def _patched_async(self, *args, **kwargs):
        kwargs["verify"] = False
        _orig_async(self, *args, **kwargs)

    _httpx.Client.__init__ = _patched_sync
    _httpx.AsyncClient.__init__ = _patched_async
