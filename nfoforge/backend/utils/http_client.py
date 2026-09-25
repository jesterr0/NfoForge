import niquests


def new_http_session() -> niquests.Session:
    """Build a niquests Session with HTTP/3 (QUIC) disabled.

    HTTP/3 negotiation has been observed to fail intermittently against some
    tracker servers, and offers no real benefit for NfoForge's request
    pattern (occasional API calls / uploads, not latency-critical traffic).
    Disabling it still allows normal HTTP/2 vs HTTP/1.1 ALPN negotiation per
    server.
    """
    return niquests.Session(disable_http3=True)
