"""Source-contract checks for the browser workspace's HTML sinks.

These tests guard the shared escaping contract; they are not a substitute for
browser-level DOM/XSS tests.
"""
from pathlib import Path


WORKSPACE = (
    Path(__file__).resolve().parents[1] / "app" / "server" / "web" / "workspace.js"
)


def test_workspace_escaper_handles_text_and_quoted_attribute_characters():
    source = WORKSPACE.read_text(encoding="utf-8")
    start = source.index("function esc(value)")
    end = source.index("\nfunction fmtDT(value)", start)
    escaper = source[start:end]

    # Ampersands must be escaped first, before introducing entities.
    assert escaper.index('.replaceAll("&", "&amp;")') < escaper.index(
        '.replaceAll("<", "&lt;")'
    )
    assert '.replaceAll(">", "&gt;")' in escaper
    assert '.replaceAll(\'"\', "&quot;")' in escaper
    assert '.replaceAll("\'", "&#39;")' in escaper


def test_workspace_uses_protected_endpoint_for_facility_metadata():
    source = WORKSPACE.read_text(encoding="utf-8")
    assert 'api("/system/metrics")' in source
    assert 'api("/health").then(h' not in source


def test_dynamic_attribute_sinks_escape_api_values():
    source = WORKSPACE.read_text(encoding="utf-8")
    assert 'value="${esc(d.id)}"' in source
    assert 'data-id="${esc(n.notification_id)}"' in source
    assert 'data-id="${esc(p.id)}"' in source
    assert 'value="${esc(p.patient_id)}"' in source
