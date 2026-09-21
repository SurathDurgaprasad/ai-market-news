from app.core.importance import (
    calibrate_importance_score,
    infer_event_signals,
    importance_band,
    normalize_importance_score,
)


EVAL = [
    (
        "NVIDIA Rubin Platform, Open Models, Autonomous Driving: NVIDIA Presents Blueprint for the Future at CES",
        "NVIDIA founder and CEO Jensen Huang took the stage at CES, declaring a platform blueprint.",
        "MAJOR",
        "hardware_platform",
    ),
    (
        "NVIDIA Releases Cosmos-H-Dreams: Real-Time Generative Simulator for Surgical Robotics",
        "NVIDIA introduced Cosmos-H-Dreams, a real-time generative simulator for surgical robotics.",
        "SIGNIFICANT",
        "capability",
    ),
    (
        "ICML 2026 Open Reproductions Hackathon Publishes 6,816 Logbooks for 2,226 Papers",
        "Community members used coding agents to reproduce ICML papers.",
        "NOTABLE",
        "research",
    ),
    (
        "Hacktron exploits libheif RCE in OpenAI forum, gains employee account access, reports to OpenAI and Discourse, receives $6,500 bounty",
        "Hacktron exploited a heap buffer overflow, achieved remote code execution, and received a bounty.",
        "SIGNIFICANT",
        "security_incident",
    ),
    (
        "Autonomous AI Agent Escapes OpenAI Sandbox and Compromises Hugging Face Infrastructure",
        "An autonomous agent escaped its sandbox and compromised infrastructure.",
        "SIGNIFICANT",
        "security_incident",
    ),
    (
        "Granite 4.2 Released: Dense Decoder-Only Reasoning LLMs in 3B, 8B, and 30B Sizes",
        "IBM released Granite 4.2, a family of dense decoder-only reasoning models in 3B, 8B, and 30B sizes.",
        "SIGNIFICANT",
        "model_family",
    ),
    (
        "Meta Releases Muse Glimmer, a 30-B Parameter Multimodal Model for Local Agentic Use",
        "Meta released Muse Glimmer, a 30-B parameter multimodal model.",
        {"NOTABLE", "SIGNIFICANT"},
        "model_release",
    ),
    (
        "NVIDIA Nemotron Achieves Benchmark-Leading Performance With LangChain Deep Agents Harness",
        "LangChain tuned its Deep Agents harness for Nemotron.",
        "SIGNIFICANT",
        "capability",
    ),
    (
        "Mistral and Mozilla Partner to Bring Open, Private, Multilingual AI to Web Browsers",
        "Mistral and Mozilla announced a partnership to integrate AI into browsers.",
        "NOTABLE",
        "partnership",
    ),
    (
        "ALTK-Evolve Matches ACE Accuracy on AppWorld with Fewer Tokens",
        "ALTK-Evolve consolidates agentic memory into guidelines.",
        "NOTABLE",
        "research",
    ),
    (
        "Mistral Assists European Energy Operator in Migrating 40,000 Lines of Fortran 77 to C++",
        "Mistral helped migrate 40,000 lines of Fortran 77 code to C++.",
        "MINOR",
        "migration",
    ),
]


def test_generic_60_does_not_survive_security_or_platform_signals():
    assert calibrate_importance_score(60, "security_incident", "platform", "significant") >= 70
    assert calibrate_importance_score(60, "hardware_platform", "ecosystem", "none") >= 90
    assert calibrate_importance_score(60, "model_family", "platform", "none") >= 70
    assert calibrate_importance_score(35, "migration", "narrow", "none") < 50
    assert 50 <= calibrate_importance_score(60, "partnership", "product", "none") < 70


def test_genuine_major_hardware_score_is_not_capped_to_significant():
    """Live NVIDIA scored Rubin 95 with scope=platform; ceiling 89 must not hide Major."""
    assert calibrate_importance_score(95, "hardware_platform", "platform", "none") >= 90
    assert importance_band(calibrate_importance_score(95, "hardware_platform", "platform", "none")) == "MAJOR"


def test_inflated_maintenance_score_is_still_compressed():
    assert calibrate_importance_score(90, "maintenance", "narrow", "none") < 50


def test_eval_corpus_inference_and_calibration():
    dumped = 60
    for headline, summary, expected, kind in EVAL:
        inf_kind, inf_scope, inf_sec = infer_event_signals(headline, summary)
        assert inf_kind == kind, (headline, inf_kind, kind)
        calibrated = calibrate_importance_score(dumped, inf_kind, inf_scope, inf_sec)
        band = importance_band(calibrated)
        if isinstance(expected, set):
            assert band in expected, (headline, band, inf_kind, inf_scope, calibrated)
        else:
            assert band == expected, (headline, band, inf_kind, inf_scope, calibrated)


def test_zero_still_means_drop():
    assert normalize_importance_score(0) is None
    assert calibrate_importance_score(0, "model_release", "ecosystem", "none") is None


def test_does_not_use_company_prestige():
    """Same kind of tool update stays minor/notable regardless of a famous vendor name in the title."""
    a = infer_event_signals("Workflow rebuilds a Gradio canvas", "The author rebuilt a workflow canvas.")
    b = infer_event_signals("NVIDIA Workflow rebuilds a Gradio canvas", "The author rebuilt a workflow canvas.")
    assert a[0] == b[0] == "tool_update"
    score_a = calibrate_importance_score(60, *a)
    score_b = calibrate_importance_score(60, *b)
    assert importance_band(score_a) == importance_band(score_b)
