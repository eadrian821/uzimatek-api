"""
JARVIS Orchestrator - The Brain
Central coordinator for all agents with intent routing and context management
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    """Classified intents for routing"""
    # Medical — standard
    MEDICAL_FLASHCARD = "medical_flashcard"
    MEDICAL_LITERATURE = "medical_literature"
    MEDICAL_QUIZ = "medical_quiz"
    MEDICAL_LOG = "medical_log"
    MEDICAL_STUDY = "medical_study"
    # Medical — cognitive brain
    MEDICAL_RECALL = "medical_recall"
    MEDICAL_DELTA = "medical_delta"
    MEDICAL_ANKI = "medical_anki"
    MEDICAL_SOCRATIC = "medical_socratic"
    MEDICAL_CRUCIBLE = "medical_crucible"
    MEDICAL_BRAIN = "medical_brain"
    MEDICAL_CAPTURE = "medical_capture"
    
    # Trading
    TRADING_BRIEF = "trading_brief"
    TRADING_SIGNAL = "trading_signal"
    TRADING_LOG = "trading_log"
    TRADING_PORTFOLIO = "trading_portfolio"
    TRADING_ALERT = "trading_alert"
    
    # Business
    BUSINESS_TENDER = "business_tender"
    BUSINESS_INVOICE = "business_invoice"
    BUSINESS_CRM = "business_crm"
    BUSINESS_PITCH = "business_pitch"
    
    # PA Operations
    PA_CALENDAR = "pa_calendar"
    PA_EMAIL = "pa_email"
    PA_TASK = "pa_task"
    PA_REMINDER = "pa_reminder"
    PA_COMMUNICATION = "pa_communication"
    PA_BRIEF = "pa_brief"
    
    # Cross-domain
    CROSS_DOMAIN = "cross_domain"
    GENERAL = "general"
    GREETING = "greeting"
    UNKNOWN = "unknown"


class AgentResponse(BaseModel):
    """Standardized response from any agent"""
    agent: str
    content: str
    confidence: float = 1.0
    actions_taken: List[Dict[str, Any]] = Field(default_factory=list)
    follow_up_needed: bool = False
    follow_up_question: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class ContextState(BaseModel):
    """Current context for decision making"""
    user_name: str = settings.user_name
    timezone: str = settings.user_timezone
    current_time: datetime = Field(default_factory=datetime.now)
    location_mode: str = "full_spectrum"
    is_trading_hours: bool = False
    is_study_block: bool = False
    active_domain: Optional[str] = None
    energy_level: Optional[float] = None
    recent_intents: List[str] = Field(default_factory=list)
    session_id: str = ""
    
    class Config:
        arbitrary_types_allowed = True


class Orchestrator:
    """
    Central orchestrator that routes requests to specialized agents
    and coordinates cross-domain intelligence
    """
    
    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.agents: Dict[str, Any] = {}
        self.context = ContextState()
        self._intent_cache: Dict[str, Tuple[Intent, float]] = {}
        
    def register_agent(self, name: str, agent: Any):
        """Register a specialized agent"""
        self.agents[name] = agent
        logger.info(f"Registered agent: {name}")
    
    async def classify_intent(self, message: str) -> Tuple[Intent, float, List[str]]:
        """
        Classify user intent using Claude for understanding
        Returns: (primary_intent, confidence, secondary_domains)
        """
        # Fast-path: command routing (no LLM needed)
        command_map = {
            "/recall": Intent.MEDICAL_RECALL,
            "/delta": Intent.MEDICAL_DELTA,
            "/anki": Intent.MEDICAL_ANKI,
            "/quiz": Intent.MEDICAL_SOCRATIC,
            "/crucible": Intent.MEDICAL_CRUCIBLE,
            "/brain": Intent.MEDICAL_BRAIN,
            "/brief": Intent.PA_BRIEF,
            "/capture": Intent.MEDICAL_CAPTURE,
        }
        for cmd, intent in command_map.items():
            if message.strip().lower().startswith(cmd):
                return intent, 1.0, []

        classification_prompt = f"""Analyze this message and classify the user's intent.

Message: "{message}"

Context:
- User: {self.context.user_name}
- Time: {self.context.current_time.strftime('%H:%M %Z')}
- Mode: {self.context.location_mode}
- Recent activity: {', '.join(self.context.recent_intents[-3:]) if self.context.recent_intents else 'None'}

Available intent categories:
MEDICAL: flashcard creation, literature search, quiz/study, clinical logging, study scheduling
MEDICAL BRAIN: recall session, delta/gap analysis, anki card generation, socratic quiz, crucible exam, clinical capture
TRADING: market brief, signal analysis, trade logging, portfolio check, price alerts
BUSINESS: tender search, invoice management, CRM/contacts, pitch deck
PA: calendar, email, tasks, reminders, communication drafts, daily briefs
GENERAL: greetings, general questions, cross-domain requests

Respond in JSON format:
{{
    "primary_intent": "CATEGORY_SPECIFIC_INTENT",
    "confidence": 0.0-1.0,
    "secondary_domains": ["domain1", "domain2"],
    "reasoning": "brief explanation"
}}

Intent codes:
- medical_flashcard, medical_literature, medical_quiz, medical_log, medical_study
- medical_recall, medical_delta, medical_anki, medical_socratic, medical_crucible, medical_brain, medical_capture
- trading_brief, trading_signal, trading_log, trading_portfolio, trading_alert
- business_tender, business_invoice, business_crm, business_pitch
- pa_calendar, pa_email, pa_task, pa_reminder, pa_communication, pa_brief
- cross_domain, general, greeting, unknown"""

        try:
            response = await self.client.messages.create(
                model=settings.claude_model_fast,
                max_tokens=500,
                messages=[{"role": "user", "content": classification_prompt}]
            )
            
            result_text = response.content[0].text
            # Extract JSON from response
            json_start = result_text.find('{')
            json_end = result_text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                result = json.loads(result_text[json_start:json_end])
                intent_str = result.get("primary_intent", "unknown").lower()
                confidence = float(result.get("confidence", 0.5))
                secondary = result.get("secondary_domains", [])
                
                try:
                    intent = Intent(intent_str)
                except ValueError:
                    intent = Intent.UNKNOWN
                
                return intent, confidence, secondary
        except Exception as e:
            logger.error(f"Intent classification error: {e}")
        
        return Intent.UNKNOWN, 0.5, []
    
    def _get_agent_for_intent(self, intent: Intent) -> Optional[str]:
        """Map intent to responsible agent"""
        intent_agent_map = {
            # Medical — standard
            Intent.MEDICAL_FLASHCARD: "medical",
            Intent.MEDICAL_LITERATURE: "medical",
            Intent.MEDICAL_QUIZ: "medical",
            Intent.MEDICAL_LOG: "medical",
            Intent.MEDICAL_STUDY: "medical",
            # Medical — cognitive brain (new)
            Intent.MEDICAL_RECALL: "delta",
            Intent.MEDICAL_DELTA: "delta",
            Intent.MEDICAL_ANKI: "atomization",
            Intent.MEDICAL_SOCRATIC: "socratic",
            Intent.MEDICAL_CRUCIBLE: "crucible",
            Intent.MEDICAL_BRAIN: "brain",
            Intent.MEDICAL_CAPTURE: "medical",
            
            # Trading
            Intent.TRADING_BRIEF: "trading",
            Intent.TRADING_SIGNAL: "trading",
            Intent.TRADING_LOG: "trading",
            Intent.TRADING_PORTFOLIO: "trading",
            Intent.TRADING_ALERT: "trading",
            
            # Business
            Intent.BUSINESS_TENDER: "business",
            Intent.BUSINESS_INVOICE: "business",
            Intent.BUSINESS_CRM: "business",
            Intent.BUSINESS_PITCH: "business",
            
            # PA
            Intent.PA_CALENDAR: "pa",
            Intent.PA_EMAIL: "pa",
            Intent.PA_TASK: "pa",
            Intent.PA_REMINDER: "pa",
            Intent.PA_COMMUNICATION: "pa",
            Intent.PA_BRIEF: "pa",
            
            # Cross-domain handled by orchestrator
            Intent.CROSS_DOMAIN: None,
            Intent.GENERAL: "pa",
            Intent.GREETING: "pa",
            Intent.UNKNOWN: "pa",
        }
        return intent_agent_map.get(intent, "pa")
    
    async def process_message(
        self, 
        message: str, 
        channel: str = "api",
        session_id: str = "",
        attachments: List[Dict] = None
    ) -> AgentResponse:
        """
        Main entry point for processing user messages
        Routes to appropriate agent(s) and synthesizes responses
        """
        start_time = datetime.now()
        self.context.session_id = session_id
        
        # Update context with current time
        self.context.current_time = datetime.now()
        self._update_trading_hours()
        
        # Classify intent
        intent, confidence, secondary_domains = await self.classify_intent(message)
        logger.info(f"Classified intent: {intent} (confidence: {confidence})")
        
        # Track intent history
        self.context.recent_intents.append(intent.value)
        if len(self.context.recent_intents) > 10:
            self.context.recent_intents = self.context.recent_intents[-10:]
        
        # Route to appropriate agent
        primary_agent_name = self._get_agent_for_intent(intent)
        
        if intent == Intent.CROSS_DOMAIN or len(secondary_domains) > 1:
            # Multi-agent coordination needed
            response = await self._handle_cross_domain(
                message, intent, secondary_domains, attachments
            )
        elif primary_agent_name and primary_agent_name in self.agents:
            # Single agent can handle
            agent = self.agents[primary_agent_name]
            response = await agent.process(
                message=message,
                intent=intent,
                context=self.context,
                attachments=attachments
            )
        else:
            # Fallback to general response
            response = await self._general_response(message)
        
        # Log processing time
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Processed message in {duration:.2f}s via {primary_agent_name or 'orchestrator'}")
        
        return response
    
    async def _handle_cross_domain(
        self,
        message: str,
        intent: Intent,
        domains: List[str],
        attachments: List[Dict] = None
    ) -> AgentResponse:
        """Handle requests that span multiple domains"""
        
        # Gather responses from relevant agents
        tasks = []
        agent_names = []
        
        for domain in domains:
            if domain in self.agents:
                agent = self.agents[domain]
                tasks.append(agent.process(
                    message=message,
                    intent=intent,
                    context=self.context,
                    attachments=attachments
                ))
                agent_names.append(domain)
        
        if not tasks:
            return await self._general_response(message)
        
        # Execute in parallel
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Synthesize responses
        valid_responses = []
        for i, resp in enumerate(responses):
            if not isinstance(resp, Exception):
                valid_responses.append((agent_names[i], resp))
            else:
                logger.error(f"Agent {agent_names[i]} error: {resp}")
        
        if not valid_responses:
            return await self._general_response(message)
        
        # Synthesize with Claude
        synthesis_prompt = f"""Synthesize these responses from different JARVIS agents into a cohesive answer.

User's question: "{message}"

Agent responses:
{chr(10).join([f"[{name}]: {resp.content}" for name, resp in valid_responses])}

Provide a unified, well-organized response that:
1. Addresses all aspects of the user's question
2. Connects insights across domains where relevant
3. Maintains a conversational, helpful tone
4. Highlights any conflicts or important nuances

Keep the response concise but comprehensive."""

        try:
            synth_response = await self.client.messages.create(
                model=settings.claude_model_balanced,
                max_tokens=1000,
                messages=[{"role": "user", "content": synthesis_prompt}]
            )
            
            combined_actions = []
            for _, resp in valid_responses:
                combined_actions.extend(resp.actions_taken)
            
            return AgentResponse(
                agent="orchestrator",
                content=synth_response.content[0].text,
                confidence=min([resp.confidence for _, resp in valid_responses]),
                actions_taken=combined_actions,
                follow_up_needed=any(resp.follow_up_needed for _, resp in valid_responses)
            )
        except Exception as e:
            logger.error(f"Synthesis error: {e}")
            # Return first valid response as fallback
            return valid_responses[0][1]
    
    async def _general_response(self, message: str) -> AgentResponse:
        """Generate a general response when no specific agent applies"""
        
        system_prompt = f"""You are JARVIS, an AI personal assistant for {self.context.user_name}.

Current context:
- Time: {self.context.current_time.strftime('%H:%M %Z on %A, %B %d')}
- Mode: {self.context.location_mode}

You assist with:
- Medical training and clinical work
- Trading and market analysis
- Business operations (Uzimatek health-tech startup)
- Personal productivity and scheduling

Be helpful, concise, and proactive. If the request is unclear, ask for clarification.
If you can help with something specific, offer to do so."""

        try:
            response = await self.client.messages.create(
                model=settings.claude_model_fast,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": message}]
            )
            
            return AgentResponse(
                agent="orchestrator",
                content=response.content[0].text,
                confidence=0.8
            )
        except Exception as e:
            logger.error(f"General response error: {e}")
            return AgentResponse(
                agent="orchestrator",
                content="I apologize, but I encountered an error processing your request. Please try again.",
                confidence=0.0
            )
    
    def _update_trading_hours(self):
        """Update trading hours based on current time"""
        import pytz
        tz = pytz.timezone(self.context.timezone)
        local_time = datetime.now(tz)
        hour = local_time.hour
        weekday = local_time.weekday()
        
        # Trading hours: roughly 8 AM - 5 PM on weekdays
        self.context.is_trading_hours = (
            weekday < 5 and 8 <= hour < 17
        )
    
    async def generate_brief(self, brief_type: str = "morning") -> AgentResponse:
        """Generate scheduled briefs by coordinating all agents"""
        
        briefs = []
        
        # Gather briefs from each agent
        for name, agent in self.agents.items():
            if hasattr(agent, 'generate_brief'):
                try:
                    brief = await agent.generate_brief(brief_type)
                    if brief:
                        briefs.append((name, brief))
                except Exception as e:
                    logger.error(f"Brief generation error for {name}: {e}")
        
        if not briefs:
            return AgentResponse(
                agent="orchestrator",
                content="No briefing data available at this time.",
                confidence=0.5
            )
        
        # Synthesize into unified brief
        brief_content = []
        if brief_type == "morning":
            brief_content.append(f"☀️ Good morning, {self.context.user_name}!\n")
        elif brief_type == "evening":
            brief_content.append(f"🌙 Evening wrap-up, {self.context.user_name}!\n")
        
        for name, brief in briefs:
            brief_content.append(f"\n**{name.upper()}**\n{brief}")
        
        return AgentResponse(
            agent="orchestrator",
            content="\n".join(brief_content),
            confidence=1.0,
            data={"brief_type": brief_type, "agents": [name for name, _ in briefs]}
        )
    
    def update_context(self, **kwargs):
        """Update orchestrator context"""
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)


# Global orchestrator instance
orchestrator = Orchestrator()
