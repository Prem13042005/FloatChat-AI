"""
src/agents/query_understanding/agent.py

FloatChat Query Understanding Agent Implementation.
Converts natural language user questions into validated QueryIntent Pydantic objects
using the provider-agnostic BaseLLMProvider abstraction layer.
"""

from typing import Optional

from src.agents.query_understanding.models import QueryIntent
from src.agents.query_understanding.prompts import QUERY_UNDERSTANDING_SYSTEM_PROMPT
from src.llm import BaseLLMProvider, get_llm_provider


class QueryUnderstandingAgent:
    """
    Agent responsible for analyzing raw natural-language user inputs, classifying query intent,
    and extracting spatial, temporal, pressure, platform, and metric slot constraints.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        """
        Initializes the QueryUnderstandingAgent.

        Args:
            llm_provider: Optional BaseLLMProvider instance.
                          If None, resolves active provider using `get_llm_provider()`.
        """
        self.llm_provider = llm_provider if llm_provider is not None else get_llm_provider()

    def analyze(self, query: str) -> QueryIntent:
        """
        Analyzes a natural-language user query string and returns a structured QueryIntent object.

        Args:
            query: Natural language ocean data prompt string.

        Returns:
            Validated QueryIntent object.

        Raises:
            ValueError: If query is empty or whitespace-only.
            LLMProviderError: If underlying LLM provider generation or validation fails.
        """
        if not query or not query.strip():
            raise ValueError("Query string cannot be empty.")

        cleaned_query = query.strip()

        # Generate structured output via BaseLLMProvider abstraction
        intent: QueryIntent = self.llm_provider.generate_structured(
            prompt=cleaned_query,
            response_model=QueryIntent,
            system_prompt=QUERY_UNDERSTANDING_SYSTEM_PROMPT,
            temperature=0.0,
        )

        return intent
