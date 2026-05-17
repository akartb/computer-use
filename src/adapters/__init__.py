"""Model adapters - OpenAI, Anthropic, Ollama."""

from src.adapters.openai_adapter import OpenAIAdapter
from src.adapters.anthropic_adapter import AnthropicAdapter
from src.adapters.ollama_adapter import OllamaAdapter

__all__ = ["OpenAIAdapter", "AnthropicAdapter", "OllamaAdapter"]
