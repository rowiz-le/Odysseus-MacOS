"""Regression tests for Deep Research report typography and export controls."""

from src.visual_report import generate_visual_report


def test_vietnamese_report_embeds_unicode_font_and_export_controls():
    report = generate_visual_report(
        question="Nghiên cứu thị trường Việt Nam",
        report_markdown=(
            "# Báo cáo tiếng Việt\n\n"
            "## Tóm tắt điều hành\n\n"
            "Nội dung có đầy đủ dấu: ă â đ ê ô ơ ư, năng lượng và nghiên cứu."
        ),
        session_id="rp-test123",
    )

    assert '<html lang="vi">' in report
    assert "font-family:'Odysseus Inter'" in report
    assert "data:font/woff2;base64," in report
    assert "Print / Save as PDF" in report
    assert 'data-export-format="html"' in report
    assert 'data-export-format="markdown"' in report
    assert 'data-export-format="json"' in report
    assert 'id="btn-back"' in report
    assert "Back to Odysseus" in report
    assert 'id="btn-open-folder"' in report
    assert "/api/research/open-export-folder" in report
    assert "await fetch(url, { credentials: 'same-origin' })" in report
    assert "URL.createObjectURL(blob)" in report
    assert "a.download = exportFilenameFromResponse(response, format)" in report
    assert "a.href = '/api/research/export/'" not in report


def test_english_report_keeps_english_language_metadata():
    report = generate_visual_report(
        question="Research renewable energy",
        report_markdown="# Energy report\n\n## Summary\n\nA concise English report.",
        session_id="rp-test456",
    )

    assert '<html lang="en">' in report
