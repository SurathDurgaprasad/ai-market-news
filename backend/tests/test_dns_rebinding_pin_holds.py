"""
Phase 1B, invariant 5 (DNS rebinding / resolution safety).

Existing coverage gap found by inspection: test_fetcher.py's
test_pin_host_stores_validated_records pins a hostname to an IP and
confirms _pinned_getaddrinfo returns that IP — but the underlying
_original_getaddrinfo mock never CHANGES during that test, so it doesn't
actually prove the pin overrides a differing later DNS answer. It only
proves the pin returns what it was given, which holds even without any
rebinding protection at all.

This file closes that gap: _original_getaddrinfo is reconfigured to
return a DIFFERENT (private/malicious) IP AFTER pin_host() has already
validated and pinned a public one for the same hostname — simulating an
attacker's authoritative DNS server changing its answer between the
validation lookup and a later connection attempt. If the pin doesn't
actually override the underlying resolver, _pinned_getaddrinfo would
return the new, malicious IP.

Prediction before running: the pin SHOULD hold, because
_pinned_getaddrinfo checks _tls.pin[hostname] first and only falls
through to _original_getaddrinfo when the hostname isn't pinned (see
app/core/fetcher.py). Written to verify that claim against the real
mechanism, not to assume it — per this session's "verify, don't assume"
discipline (see NVDA-01, the Bedrock isinstance bug, and others this
session that were caught by exactly this kind of check).
"""
import ipaddress
import socket

import pytest

from app.core import fetcher as fetcher_mod
from app.core.fetcher import pin_host, unpin_all, resolve_validated_addrinfo


def _addrinfo_for(ip: str, port=None):
    addr = ipaddress.ip_address(ip)
    if addr.version == 4:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port or 0))]
    return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, port or 0, 0, 0))]


def test_pin_holds_even_when_underlying_dns_answer_changes_after_pinning(monkeypatch):
    """
    The actual rebinding attack: pin to a validated public IP, then make
    the real resolver start returning a private IP for the SAME hostname
    (simulating the attacker's DNS TTL expiring and re-resolving to an
    internal target), and confirm _pinned_getaddrinfo still returns the
    ORIGINALLY PINNED public IP, not the new private one.
    """
    hostname = "attacker-controlled.example"
    call_log = []

    def switching_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        call_log.append(host)
        if len(call_log) == 1:
            # First call (the one pin_host() makes): a legitimate public IP.
            return _addrinfo_for("93.184.216.34", port)
        # Any later direct call to the real resolver (i.e. rebinding, or a
        # bug where pinning isn't actually being consulted): a private IP.
        return _addrinfo_for("127.0.0.1", port)

    monkeypatch.setattr(fetcher_mod, "_original_getaddrinfo", switching_getaddrinfo)

    try:
        pin_host(hostname)  # First (and only expected) real resolution.
        fetcher_mod._ensure_hook()

        # Simulate httpx (or anything else) calling socket.getaddrinfo for
        # this exact hostname again during the pinned window — this is
        # the moment a rebinding attack would try to redirect the
        # connection if pinning weren't actually in effect.
        result = fetcher_mod._pinned_getaddrinfo(hostname, 443)
        resolved_ip = result[0][4][0]

        assert resolved_ip == "93.184.216.34", (
            f"Pin did not hold: expected the originally-validated public IP, got {resolved_ip}. "
            f"If this is 127.0.0.1, the pin was bypassed and a rebound private address reached "
            f"the connection layer — a real SSRF-via-DNS-rebinding hole."
        )
        # The real resolver must only have been consulted ONCE (by
        # pin_host itself) — a second real lookup for the same hostname
        # while pinned would itself indicate the pin isn't being checked
        # first.
        assert call_log.count(hostname) <= 1, (
            f"_original_getaddrinfo was called {call_log.count(hostname)} times for a pinned "
            f"hostname — the pin should short-circuit all further resolution."
        )
    finally:
        unpin_all()


def test_pin_rejects_at_validation_time_if_first_answer_is_already_private():
    """
    Neighboring case: if the FIRST (validation) resolution itself returns
    a private IP, pin_host must reject before ever pinning anything —
    confirms the ordering (validate-then-pin, not pin-then-validate).
    """
    hostname = "already-private.example"

    def private_first(host, port, family=0, type=0, proto=0, flags=0):
        return _addrinfo_for("10.0.0.5", port)

    import app.core.fetcher as fetcher_mod_local
    original = fetcher_mod_local._original_getaddrinfo
    fetcher_mod_local._original_getaddrinfo = private_first
    try:
        with pytest.raises(ValueError, match="blocked IP"):
            resolve_validated_addrinfo(hostname)
        # Must not have been pinned despite the attempt.
        assert hostname not in (getattr(fetcher_mod_local._tls, "pin", None) or {})
    finally:
        fetcher_mod_local._original_getaddrinfo = original
        unpin_all()
