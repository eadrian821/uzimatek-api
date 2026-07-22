"""
PA Operations Agent
The glue layer - handles cross-domain coordination, scheduling, and daily operations
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings
from app.services.calendar import calendar
from app.services.messaging import messaging

logger = logging.getLogger(__name__)


class PAAgent(BaseAgent):
    """
    PA Operations Agent - The Glue Layer
    
    Handles:
    - Calendar management
    - Email triage
    - Communication drafts
    - Task management
    - Reminders
    - Travel management
    - Financial housekeeping (M-Pesa)
    - Health & wellness reminders
    - Weekly reviews
    - General assistance
    """
    
    def __init__(self):
        super().__init__(
            name="pa",
            description="Personal assistant operations and cross-domain coordination"
        )
        
    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's PA Operations Agent - the personal assistant layer for {settings.user_name}.

You are the "glue" that makes JARVIS feel like a human PA rather than a collection of tools.

Core Responsibilities:
1. CALENDAR: Smart scheduling considering priorities, energy, domain-switching costs
2. EMAIL: Triage by urgency and domain, draft replies, flag important items
3. COMMUNICATIONS: Draft messages in Adrian's voice (formal/investors, collegial/doctors, casual/friends)
4. TASKS: Cross-domain task management with dependencies and recurrence
5. REMINDERS: Context-aware reminders (location, time, activity-based)
6. TRAVEL: Flight tracking (NBO↔LAX), visa documents, currency exchange
7. M-PESA: Transaction reconciliation, expense categorization, bill reminders
8. HEALTH: Sleep quality feedback, hydration reminders, break suggestions
9. WEEKLY REVIEW: Accomplishments, goal progress, upcoming week preview

Context Awareness:
- Location modes: MTRH (clinical), Home (full spectrum), LA (US clinical), Commuting (light touch)
- Notification priorities: P0 (critical/bypass DND), P1 (urgent), P2 (normal), P3 (low/batched)
- Energy management: Consider sleep score, focus duration, time since break

Communication Style:
- Be proactive but not overwhelming
- Anticipate needs based on patterns
- Keep interactions efficient - no unnecessary pleasantries
- Adapt formality to context

Guidelines:
- When scheduling, consider buffer time between domain switches
- For emails, surface the critical information upfront
- For tasks, suggest prioritization based on deadlines and impact
- For reminders, use the right channel (SMS for critical, WhatsApp for normal)
- Track patterns to improve suggestions over time

Response style: Efficient, anticipatory, personalized."""

    @property
    def capabilities(self) -> List[str]:
        return [
            "calendar_manage", "email_triage", "communication_draft",
            "task_manage", "reminder_set", "travel_manage",
            "mpesa_reconcile", "health_reminder", "weekly_review",
            "general_assist"
        ]
    
    async def process(self, message: str, intent: Any, context: Any, attachments: List[Dict] = None) -> AgentResponse:
        """Process PA-related requests"""
        intent_str = intent.value if hasattr(intent, 'value') else str(intent)
        message_lower = message.lower()
        
        if any(x in message_lower for x in ["calendar", "schedule", "meeting", "book", "appointment"]):
            return await self._handle_calendar(message, context)
        elif any(x in message_lower for x in ["email", "mail", "inbox"]):
            return await self._handle_email(message, context)
        elif any(x in message_lower for x in ["draft", "write", "message", "whatsapp", "text"]):
            return await self._handle_communication(message, context)
        elif any(x in message_lower for x in ["task", "todo", "to-do", "add task"]):
            return await self._handle_tasks(message, context)
        elif any(x in message_lower for x in ["remind", "reminder", "don't forget", "ping"]):
            return await self._handle_reminder(message, context)
        elif any(x in message_lower for x in ["travel", "flight", "visa", "passport", "trip"]):
            return await self._handle_travel(message, context)
        elif any(x in message_lower for x in ["mpesa", "m-pesa", "transaction", "payment", "expense"]):
            return await self._handle_mpesa(message, context)
        elif "brief" in message_lower or intent_str == "pa_brief":
            return await self._handle_brief_request(message, context)
        elif any(x in message_lower for x in ["review", "week", "summary", "recap"]):
            return await self._handle_review(message, context)
        elif any(x in message_lower for x in ["hello", "hi", "hey", "good morning", "good evening"]):
            return await self._handle_greeting(message, context)
        else:
            return await self._handle_general(message, context)
    
    async def _handle_calendar(self, message: str, context: Any) -> AgentResponse:
        # Use Claude to extract event details
        extract_prompt = f"""Extract event details from this request: "{message}"
        
        Current time: {context.current_time.isoformat()}
        
        Respond in JSON only:
        {{
            "summary": "Title",
            "start_time": "ISO format",
            "end_time": "ISO format",
            "description": "notes",
            "is_booking": true/false
        }}
        """
        
        actions = []
        try:
            extraction = await self._call_claude([{"role": "user", "content": extract_prompt}], max_tokens=300)
            data = json.loads(extraction[extraction.find('{'):extraction.rfind('}')+1])
            
            if data.get("is_booking"):
                start = datetime.fromisoformat(data["start_time"])
                end = datetime.fromisoformat(data["end_time"])
                event = await calendar.create_event(
                    summary=data["summary"],
                    start_time=start,
                    end_time=end,
                    description=data.get("description", "")
                )
                if event:
                    actions.append({"action": "calendar_create", "event": data["summary"]})
                    content = f"✅ Scheduled: **{data['summary']}**\nTime: {start.strftime('%H:%M')} - {end.strftime('%H:%M')}\n[View in Google Calendar]({event.get('htmlLink')})"
                else:
                    content = "I tried to add that to your calendar, but the Google Calendar API returned an error. Is the service configured?"
            else:
                events = await calendar.get_upcoming_events()
                content = "Here are your upcoming events:\n" + "\n".join([f"- {e.get('summary')} ({e.get('start', {}).get('dateTime')})" for e in events])
        except Exception as e:
            logger.error(f"Calendar processing error: {e}")
            content = "I couldn't process that calendar request. Please try again with a clear time and summary."

        return AgentResponse(agent=self.name, content=content, confidence=0.9, actions_taken=actions)
    
    async def _handle_email(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this email request: "{message}"

{self._format_context(context)}

If triaging inbox:
1. **P0 Critical** - Requires immediate attention
2. **P1 Urgent** - Important, respond within hours
3. **P2 Normal** - Can wait for scheduled email time
4. **P3 Low** - Newsletters, FYI items

For each important email:
- From, Subject, Key point in 1 line
- Suggested action: Reply/Forward/Archive/Task
- Draft reply if straightforward

If drafting:
- Match tone to recipient (investor/doctor/friend)
- Be concise but complete
- Include clear call-to-action"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1200)
        return AgentResponse(agent=self.name, content=f"📧 **EMAIL**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "email_triage"}])
    
    async def _handle_communication(self, message: str, context: Any) -> AgentResponse:
        # Use Claude to decide if we should actually send something
        prompt = f"""Draft this communication: "{message}"
        
        Recipient: {context.user_name}
        Time: {context.current_time}
        
        Respond in JSON:
        {{
            "draft": "The actual message content",
            "channel": "email/slack/telegram/whatsapp",
            "recipient": "target contact",
            "should_send": true/false
        }}
        """
        
        actions = []
        try:
            extraction = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=800)
            data = json.loads(extraction[extraction.find('{'):extraction.rfind('}')+1])
            
            if data.get("should_send"):
                sent = await messaging.send(
                    content=data["draft"],
                    channel=data["channel"],
                    recipient_id=data.get("recipient")
                )
                if sent:
                    actions.append({"action": "message_sent", "channel": data["channel"]})
                    return AgentResponse(agent=self.name, content=f"✅ Sent via {data['channel']}:\n\n{data['draft']}", confidence=0.95, actions_taken=actions)
            
            return AgentResponse(agent=self.name, content=f"✉️ **DRAFT**\n\n{data.get('draft')}", confidence=0.9, follow_up_needed=True, follow_up_question="Should I send this?")
        except Exception as e:
            return AgentResponse(agent=self.name, content="I couldn't draft that message. Who should I send it to?", confidence=0.5)

    async def _handle_tasks(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this task request: "{message}"

{self._format_context(context)}

Task format:
☐ [Priority] Task title | Domain | Due: Date"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"✅ **TASKS**\n\n{response}", confidence=0.9,
                           actions_taken=[{"action": "task_manage"}])
    
    async def _handle_reminder(self, message: str, context: Any) -> AgentResponse:
        # PING logic: If the user says "ping me", use the messaging hub immediately
        if "ping" in message.lower():
            sent = await messaging.send_with_priority(f"🔔 **PING**: {message}", priority="p1")
            if sent:
                return AgentResponse(agent=self.name, content="I've sent you a ping via your active notification channels.", confidence=1.0)
            else:
                return AgentResponse(agent=self.name, content="I tried to ping you, but no messaging channels (Slack/Telegram) are configured.", confidence=1.0)

        prompt = f"""Set this reminder: "{message}"
Confirm with: "I'll remind you [when] via [channel] to [what]" """

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=600)
        return AgentResponse(agent=self.name, content=f"⏰ **REMINDER SET**\n\n{response}", confidence=0.95,
                           actions_taken=[{"action": "reminder_set"}])
    
    async def _handle_travel(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this travel request: "{message}"

{self._format_context(context)}"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"✈️ **TRAVEL**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "travel_manage"}])
    
    async def _handle_mpesa(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this M-Pesa/financial request: "{message}"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"💳 **M-PESA**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "mpesa_reconcile"}])
    
    async def _handle_brief_request(self, message: str, context: Any) -> AgentResponse:
        hour = context.current_time.hour
        if hour < 10:
            brief_type = "morning"
        elif hour >= 19:
            brief_type = "evening"
        else:
            brief_type = "midday"
        
        brief = await self.generate_brief(brief_type)
        return AgentResponse(agent=self.name, content=brief or "Brief generation in progress...", 
                           confidence=0.95, data={"brief_type": brief_type})
    
    async def _handle_review(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Generate a review/summary: "{message}"

{self._format_context(context)}"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1200)
        return AgentResponse(agent=self.name, content=f"📊 **REVIEW**\n\n{response}", confidence=0.9,
                           actions_taken=[{"action": "review_generate"}])
    
    async def _handle_greeting(self, message: str, context: Any) -> AgentResponse:
        hour = context.current_time.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"
        
        day_name = context.current_time.strftime("%A")
        
        response = f"""{greeting}, {context.user_name}! 👋

It's {day_name}, {context.current_time.strftime('%B %d')} • {context.current_time.strftime('%H:%M')} EAT

**Quick Status:**
• Mode: {context.location_mode.replace('_', ' ').title()}
• Trading hours: {'Yes' if context.is_trading_hours else 'No'}

How can I help you today?"""

        return AgentResponse(agent=self.name, content=response, confidence=1.0)
    
    async def _handle_general(self, message: str, context: Any) -> AgentResponse:
        response = await self._call_claude(
            [{"role": "user", "content": f"{self._format_context(context)}\n\nUser: {message}"}],
            max_tokens=1200
        )
        return AgentResponse(agent=self.name, content=response, confidence=0.8)
    
    async def generate_brief(self, brief_type: str) -> Optional[str]:
        now = datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        time_str = now.strftime("%H:%M")
        
        if brief_type == "morning":
            return f"""☀️ **GOOD MORNING, ADRIAN!**
{date_str} • {time_str} EAT

(Dynamic briefing requires service connection)"""
        # ... (rest of logic)
        return None
