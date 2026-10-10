"""The packaged server (src/fintable_mcp/server.py — what `pip install fintable-mcp` and the
`fintable-mcp` console script run) must be byte-identical to the top-level fintable_mcp.py the
other tests import.

SM 1219369367770772 (2026-10-10): three fixes (bba826b /login refusal, 215ee50 rule-row parse,
b5c6c99 Livewire render) landed only in the top-level copy, so the tests went green while the
shipped package still answered total=0. Edit one, copy it to the other.
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_packaged_server_matches_top_level():
    with open(os.path.join(ROOT, "fintable_mcp.py"), "rb") as a, \
         open(os.path.join(ROOT, "src", "fintable_mcp", "server.py"), "rb") as b:
        assert a.read() == b.read(), (
            "src/fintable_mcp/server.py drifted from fintable_mcp.py -- "
            "cp fintable_mcp.py src/fintable_mcp/server.py")
