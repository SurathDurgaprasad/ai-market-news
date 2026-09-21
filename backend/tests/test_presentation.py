from app.core.presentation import (
    classify_image_role,
    present_citations,
    strip_wrapping_quotes,
)
from app.core.deduplication import verify_citations


def test_strip_wrapping_quotes_already_quoted():
    assert strip_wrapping_quotes('"The model achieves 79% accuracy."') == "The model achieves 79% accuracy."
    assert strip_wrapping_quotes("“The model achieves 79% accuracy.”") == "The model achieves 79% accuracy."
    assert strip_wrapping_quotes("\"\"The model achieves 79% accuracy.\"\"") == "The model achieves 79% accuracy."


def test_strip_wrapping_quotes_unquoted():
    assert strip_wrapping_quotes("The model achieves 79% accuracy.") == "The model achieves 79% accuracy."


def test_strip_wrapping_quotes_keeps_apostrophes():
    assert strip_wrapping_quotes("Don't skip the model's result.") == "Don't skip the model's result."
    assert strip_wrapping_quotes("'Don't skip the model's result.'") == "Don't skip the model's result."


def test_present_citations_multiple():
    presented = present_citations(
        [
            '"First quote from the source text."',
            "Second quote from the source text.",
            "“Third quote from the source text.”",
            "",
            None,
        ]
    )
    assert presented == [
        "First quote from the source text.",
        "Second quote from the source text.",
        "Third quote from the source text.",
    ]


def test_verify_citations_strips_wrapping_quotes_on_persist():
    content = "The model achieves 79% accuracy. Don't skip this measured result."
    assert verify_citations(content, ['"The model achieves 79% accuracy."']) == [
        "The model achieves 79% accuracy."
    ]
    assert verify_citations(content, ["The model achieves 79% accuracy."]) == [
        "The model achieves 79% accuracy."
    ]
    assert verify_citations(content, ["Don't skip this measured result."]) == [
        "Don't skip this measured result."
    ]
    verified = verify_citations(
        content,
        [
            "“The model achieves 79% accuracy.”",
            "Don't skip this measured result.",
        ],
    )
    assert verified == [
        "The model achieves 79% accuracy.",
        "Don't skip this measured result.",
    ]


def test_classify_image_role_from_url_evidence():
    assert classify_image_role(None) == "none"
    assert classify_image_role("") == "none"
    assert (
        classify_image_role(
            "https://opengraph.githubassets.com/757edfa22c8cec63243b6db8691aa148bbcede35b72fb0f10a038fa3aa43da14/jemalloc/jemalloc"
        )
        == "none"
    )
    assert (
        classify_image_role("https://example.com/static/logo.png")
        == "none"
    )
    assert (
        classify_image_role(
            "https://blogs.nvidia.com/wp-content/uploads/2026/07/Nemotron_LangChain-scaled.jpg"
        )
        == "hero"
    )
    assert (
        classify_image_role(
            "https://huggingface.co/blog/assets/asyncgrpo-lora-hfjobs/thumbnail.png"
        )
        == "source"
    )
    assert (
        classify_image_role(
            "https://cdn-uploads.huggingface.co/production/uploads/6435a1131860001f144239ea/dI5J2sSc3TSprk9VB4EVJ.jpeg"
        )
        == "source"
    )
    assert classify_image_role("https://www.hacktron.ai/_astro/CwjuS_y3.png") == "source"
