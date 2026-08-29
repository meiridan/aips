"""Maya Core — chat orchestrator + memory layer."""

__version__ = "1.0.0"

# Trust the OS certificate store for every outbound TLS connection, so the
# Zscaler MITM root installed on the dev machine is honoured WITHOUT turning
# verification off. Must run before any HTTP client is constructed — every
# script in scripts/ and tools/ does the same thing for the same reason.
#
# A prior version monkeypatched httpx.Client.__init__ to force verify=False
# whenever SSL_CERT_FILE was set. That disabled certificate verification for
# every xAI / OpenAI / mem0 / Telegram call in local dev (SSL_CERT_FILE is
# exported from the developer's shell profile) while its comment claimed the
# opposite. Do not reintroduce it.
try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 - fall back to certifi; verification stays ON
    pass
