"""
Base Agent Class
Foundation for all specialized JARVIS agents
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.core.config import settings


logger = logging.getLogger(__name__)


class AgentResponse(BaseModel):
    """Standardized response from any agent"""
    agent: str
    content: str
    confidence: float = 1.0
    actions_taken: List[Dict[str, Any]] = []
    follow_up_needed: bool = False
    follow_up_question: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class BaseAgent(ABC):
    """
    Abstract base class for all JARVIS agents.
    Provides common functionality and interface definition.
    """

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model_fast = settings.claude_model_fast        # Haiku — classification, triage
        self.model_balanced = settings.claude_model_balanced  # Sonnet — analysis, synthesis
        self.model_complex = settings.claude_model_complex  # Opus — deep reasoning
        self.model_fable = settings.claude_model_fable      # Fable 5 — clinical coding, fraud, pre-auth

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the agent's system prompt"""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> List[str]:
        """Return list of agent capabilities"""
        pass

    @abstractmethod
    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        """Process a user message and return response"""
        pass

    async def generate_brief(self, brief_type: str) -> Optional[str]:
        """Generate a scheduled brief - override in subclasses"""
        return None

    async def _call_claude(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        use_complex_model: bool = False,
        use_balanced_model: bool = False,
        use_fable_model: bool = False,
        max_tokens: int = 1000,
        thinking_budget: int = 0,
    ) -> str:
        """Make a call to Claude API.

        Fable 5 is a reasoning model that may return ThinkingBlock objects before
        the TextBlock in response.content. We always iterate to find the text block
        rather than blindly accessing index 0.

        If use_fable_model=True and the Fable 5 call fails for any reason (model
        not accessible, API error), automatically retries with claude-sonnet-4-6
        so the pipeline continues even when Fable 5 is unavailable.
        """
        if use_fable_model:
            model = self.model_fable
        elif use_complex_model:
            model = self.model_complex
        elif use_balanced_model:
            model = self.model_balanced
        else:
            model = self.model_fast

        kwargs: Dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            system=system or self.system_prompt,
            messages=messages,
        )

        # Fable 5 uses adaptive thinking by default — do NOT pass "enabled"/budget_tokens.
        # Other extended-thinking models (Opus 4) use the "enabled" mode.
        if not use_fable_model and thinking_budget > 0:
            budget = min(thinking_budget, max_tokens - 200)
            if budget > 0:
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}

        try:
            response = await self.client.messages.create(**kwargs)
            for block in response.content:
                if block.type == "text":
                    return block.text
            raise ValueError(
                f"[{self.name}] No text block in response from {model}. "
                f"Content types: {[b.type for b in response.content]}"
            )
        except Exception as e:
            if use_fable_model:
                # Fable 5 inaccessible (wrong API key tier, model unavailable, etc.)
                # Fall back to Sonnet so the pipeline continues producing output.
                logger.warning(
                    f"[{self.name}] Fable 5 call failed ({type(e).__name__}: {e}). "
                    f"Retrying with {self.model_balanced}."
                )
                try:
                    fb_kwargs: Dict[str, Any] = dict(
                        model=self.model_balanced,
                        max_tokens=max_tokens,
                        system=system or self.system_prompt,
                        messages=messages,
                    )
                    fb_response = await self.client.messages.create(**fb_kwargs)
                    for block in fb_response.content:
                        if block.type == "text":
                            return block.text
                    raise ValueError(
                        f"[{self.name}] No text block in Sonnet fallback response."
                    )
                except Exception as fb_e:
                    logger.error(f"[{self.name}] Sonnet fallback also failed: {fb_e}")
                    raise fb_e
            logger.error(f"Claude API error in {self.name}: {e}")
            raise
    
    async def _call_claude_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: List[Dict],
        system: str = None,
        use_complex_model: bool = False,
        max_tokens: int = 1000
    ) -> Dict:
        """Make a call to Claude API with tool use"""
        try:
            model = self.model_complex if use_complex_model else self.model_fast
            
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system or self.system_prompt,
                messages=messages,
                tools=tools
            )
            
            # Parse response for tool use
            result = {
                "content": "",
                "tool_calls": []
            }
            
            for block in response.content:
                if block.type == "text":
                    result["content"] = block.text
                elif block.type == "tool_use":
                    result["tool_calls"].append({
                        "id": block.id,
                        "name": block.name,
                        "input": block.input
                    })
            
            return result
        except Exception as e:
            logger.error(f"Claude API tool error in {self.name}: {e}")
            raise
    
    def _format_context(self, context: Any) -> str:
        """Format context for inclusion in prompts"""
        return f"""Current Context:
- User: {context.user_name}
- Time: {context.current_time.strftime('%H:%M %Z on %A, %B %d, %Y')}
- Mode: {context.location_mode}
- Trading Hours: {'Yes' if context.is_trading_hours else 'No'}
- Study Block: {'Yes' if context.is_study_block else 'No'}"""
    
    def _log_action(self, action: str, details: Dict = None):
        """Log an action taken by the agent"""
        logger.info(f"[{self.name}] Action: {action} | Details: {details}")
