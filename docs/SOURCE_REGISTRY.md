# Source Registry

This document lists the initial monitoring ecosystem targets required by the project directive.
The architecture must be flexible to add to this list without code changes (data-driven registry).

**Current seeded status:** `backend/seed_sources.py` currently seeds
~22 sources (OpenAI, Anthropic, Google AI, Google DeepMind, Meta AI,
Microsoft Research, Mistral AI, xAI, DeepSeek, Cohere, Perplexity AI,
Stability AI, Hugging Face, NVIDIA, AWS AI, plus general tech journalism:
TechCrunch, The Verge, Wired, Ars Technica, VentureBeat, MIT Technology
Review, Hacker News). The 37-item watchlist below is the target scope,
not a claim that every entry is already configured — items like Moonshot
AI, Qwen/Alibaba, ByteDance, Tencent, Baidu, Zhipu AI, MiniMax, AI21 Labs,
Runway, Midjourney, ElevenLabs, Cursor, Windsurf, Cline, LangChain,
CrewAI, OpenHands, and the MCP ecosystem are on the target list but not
yet in `seed_sources.py`. Adding them is a data change (run the seed
script with new entries), not a code change — consistent with the
data-driven registry goal.

## Initial Watchlist

1. **OpenAI** (Primary)
2. **xAI**
3. **Moonshot AI**
4. **Qwen / Alibaba**
5. **Mistral AI**
6. **Meta AI**
7. **Google / Gemini**
8. **Anthropic**
9. **Hugging Face**
10. **NVIDIA**
11. **Microsoft**
12. **Amazon / AWS**
13. **Apple**
14. **Google DeepMind**
15. **Perplexity**
16. **Cohere**
17. **DeepSeek**
18. **ByteDance**
19. **Tencent**
20. **Baidu**
21. **Zhipu AI**
22. **MiniMax**
23. **AI21 Labs**
24. **Stability AI**
25. **Runway**
26. **Midjourney**
27. **ElevenLabs**
28. **Cursor**
29. **Windsurf**
30. **Cline**
31. **OpenCode / current successor ecosystem**
32. **LangChain**
33. **CrewAI**
34. **OpenHands**
35. **MCP ecosystem**
36. **NVIDIA ecosystem**
37. **Major open-source AI GitHub projects**

## Source Tiers

1. **Primary Sources**: Official company blogs, documentation, GitHub releases, PRs, technical papers.
2. **Secondary Sources**: Trusted tech journalism (Reuters, TechCrunch, Bloomberg).
3. **Community Sources**: Hacker News, Reddit (requires high similarity mapping to a primary source, otherwise treated as unverified).
