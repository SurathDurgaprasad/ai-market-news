import os
import asyncio
from typing import List, Dict

# Set up path so we can import from app
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.providers.llm import get_llm_provider, NVIDIAProvider, OpenAIProvider, TestLLMProvider
from app.core.runtime import is_test_runtime

FIXTURES: List[Dict[str, str]] = [
    {
        "name": "MAJOR frontier model release",
        "expect": "90-100",
        "content": "OpenAI has officially released GPT-5. The new model demonstrates human-level reasoning across all benchmarks and is available via API today.",
    },
    {
        "name": "MAJOR AI hardware",
        "expect": "70-100",
        "content": "NVIDIA announced the B300 GPU for training frontier models, with 2x the memory bandwidth of B200, shipping to cloud providers this quarter.",
    },
    {
        "name": "MAJOR regulation",
        "expect": "70-100",
        "content": "The European Union's AI Act high-risk obligations enter into force today, requiring foundation model providers to publish training data summaries.",
    },
    {
        "name": "SIGNIFICANT open-source model",
        "expect": "70-89",
        "content": "Meta releases Llama 4, a new 400B parameter open-source frontier model that beats GPT-4 on coding tasks.",
    },
    {
        "name": "SIGNIFICANT API release",
        "expect": "50-89",
        "content": "Anthropic launched a new Messages API batch endpoint with 50% lower cost for asynchronous workloads.",
    },
    {
        "name": "NOTABLE funding",
        "expect": "50-69",
        "content": "AI startup Anthropic raises $2 billion in Series C funding to expand their compute infrastructure.",
    },
    {
        "name": "MINOR product feature",
        "expect": "1-49",
        "content": "Google adds a new summarization feature to Google Docs powered by Gemini.",
    },
    {
        "name": "MINOR marketing",
        "expect": "1-29",
        "content": "Our CEO is excited to share that we are committed to responsible AI and partnering with industry leaders this quarter.",
    },
    {
        "name": "NOISE listicle",
        "expect": "0-29",
        "content": "Top 10 AI tools you must try this weekend to 10x your productivity! Number 4 will shock you.",
    },
]

async def main():
    if is_test_runtime():
        print("Skipping calibration validation: test runtime would use TestLLMProvider.")
        return

    provider = get_llm_provider()
    if isinstance(provider, TestLLMProvider):
        print("FAILED: calibration must not use TestLLMProvider.")
        return
    if not isinstance(provider, (NVIDIAProvider, OpenAIProvider)):
        print(f"Skipping calibration validation: no usable production provider ({type(provider).__name__}).")
        return
        
    print(f"Validating Importance Classification Calibration via {type(provider).__name__}...\n")
    
    for fixture in FIXTURES:
        print(f"Testing Scenario: {fixture['name']}")
        print(f"Content: {fixture['content']}")
        try:
            classification = provider.classify_event(fixture["content"])
            print(f"--> Assigned Score: {classification.importance_score}")
            print(f"--> Reasoning: {classification.importance_reasoning}\n")
        except Exception as e:
            print(f"--> Error: {e}\n")

if __name__ == "__main__":
    asyncio.run(main())
