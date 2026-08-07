"""VoxEngine multi-agent pipeline — agent modules.

Agent 1: Structure Parser (rule-based, $0)
Agent 2: Character Attribution (Llama-3.2-3B via Ollama)
Agent 3: Text Normalizer (gpt-4o-mini / Qwen2.5-7B)
Agent 4: Prosody & Emotion Planner (Phi-3.5-mini / Gemma-2-2B)
Agent 5: QA Consistency Validator (gpt-4o-mini batch)
"""
