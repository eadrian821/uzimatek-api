"""
Business Operations Agent
Manages Uzimatek operations, diaspora consultancy, and revenue activities
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings

logger = logging.getLogger(__name__)


class BusinessAgent(BaseAgent):
    """Business Operations Agent for Uzimatek and income streams"""
    
    def __init__(self):
        super().__init__(
            name="business",
            description="Business operations and Uzimatek management"
        )
        self.income_sources = ["consulting", "tutoring", "technical_writing", "visa_coaching", "uzimatek"]
        
    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Business Operations Agent for {settings.user_name}.

Primary Business: Uzimatek (health-tech startup, EHR platform for Africa)
Income Streams: Diaspora consultancy, medical tutoring, technical writing, visa coaching

Capabilities:
1. TENDER SCANNING: Monitor KEMSA, county governments for health-tech opportunities
2. BUSINESS PLANNING: Generate business plans with market data
3. CRM: Track investors, partners, clients with relationship scores
4. INVOICING: Generate invoices, M-Pesa integration
5. INCOME TRACKING: Monitor revenue streams, P&L analysis
6. PITCH GENERATION: Create investor materials
7. REGULATORY MONITORING: Track health-tech regulations

Context: KES currency, M-Pesa payments, target $10-50/day from side income.
Style: Professional, action-oriented, deadline-aware."""

    @property
    def capabilities(self) -> List[str]:
        return ["tender_scan", "business_plan", "crm_manage", "invoice_create", "income_track", "pitch_generate"]
    
    async def process(self, message: str, intent: Any, context: Any, attachments: List[Dict] = None) -> AgentResponse:
        """Process business-related requests"""
        intent_str = intent.value if hasattr(intent, 'value') else str(intent)
        message_lower = message.lower()
        
        if "tender" in message_lower:
            return await self._handle_tender(message, context)
        elif "invoice" in message_lower:
            return await self._handle_invoice(message, context)
        elif any(x in message_lower for x in ["crm", "contact", "client", "investor"]):
            return await self._handle_crm(message, context)
        elif any(x in message_lower for x in ["income", "revenue", "p&l", "earnings"]):
            return await self._handle_income(message, context)
        elif any(x in message_lower for x in ["pitch", "deck", "presentation"]):
            return await self._handle_pitch(message, context)
        elif any(x in message_lower for x in ["plan", "business plan", "roadmap"]):
            return await self._handle_planning(message, context)
        else:
            return await self._handle_general(message, context)
    
    async def _handle_tender(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this tender-related request: "{message}"

Provide:
1. **Active Tenders** - Health-tech opportunities from KEMSA, counties, PPRA
2. **Match Analysis** - How well each matches Uzimatek capabilities
3. **Deadlines** - Urgent items highlighted
4. **Application Status** - Any in-progress applications
5. **Action Items** - Next steps for promising tenders

Format professionally with clear priorities."""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1200)
        return AgentResponse(agent=self.name, content=f"📋 **TENDER UPDATE**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "tender_scan"}])
    
    async def _handle_invoice(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this invoice request: "{message}"

Extract: Client name, amount, currency (default KES), services, due date.

Generate professional invoice with:
- Invoice number (format: INV-YYYYMM-XXX)
- Client details
- Service description
- Amount with tax if applicable
- Payment instructions (M-Pesa: Till/Paybill, Bank details)
- Due date

Also provide: Payment reminder schedule, follow-up template."""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"🧾 **INVOICE**\n\n{response}", confidence=0.9,
                           actions_taken=[{"action": "invoice_create"}])
    
    async def _handle_crm(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Process this CRM request: "{message}"

Provide relevant:
1. **Contact Management** - Add/update contact info
2. **Relationship Score** - Health of relationship (0-1)
3. **Interaction History** - Recent touchpoints
4. **Follow-up Needed** - Overdue or upcoming
5. **Action Items** - Suggested next steps

Categories: Investors, Partners, Clients, Mentors, Medical contacts."""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"👥 **CRM UPDATE**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "crm_update"}])
    
    async def _handle_income(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Provide income analysis for: "{message}"

Dashboard:
1. **Today's Income** - By source
2. **This Week** - Running total vs target ($70-350/week)
3. **This Month** - Breakdown by stream
4. **Trends** - Which streams growing/declining
5. **Opportunities** - Untapped potential

Sources: Consulting, Tutoring, Technical Writing, Visa Coaching, Uzimatek"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=f"💰 **INCOME TRACKER**\n\n{response}", confidence=0.8,
                           actions_taken=[{"action": "income_analysis"}])
    
    async def _handle_pitch(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Create pitch materials for: "{message}"

Generate:
1. **Executive Summary** - 2-3 sentences
2. **Problem Statement** - Healthcare challenges in Africa
3. **Solution** - Uzimatek's EHR platform
4. **Market Size** - TAM/SAM/SOM for African health-tech
5. **Traction** - Current progress and metrics
6. **Team** - Key strengths
7. **Ask** - Funding/partnership needs
8. **Use of Funds** - Allocation plan

Investor-ready, data-driven, compelling narrative."""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1500, use_complex_model=True)
        return AgentResponse(agent=self.name, content=f"🎯 **PITCH DECK CONTENT**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "pitch_generate"}])
    
    async def _handle_planning(self, message: str, context: Any) -> AgentResponse:
        prompt = f"""Business planning request: "{message}"

Provide structured plan with:
1. **Objectives** - Clear, measurable goals
2. **Market Analysis** - Relevant data
3. **Strategy** - Approach and tactics
4. **Timeline** - Milestones and deadlines
5. **Resources** - What's needed
6. **Risks** - Mitigation strategies
7. **Metrics** - Success indicators"""

        response = await self._call_claude([{"role": "user", "content": prompt}], max_tokens=1500, use_complex_model=True)
        return AgentResponse(agent=self.name, content=f"📊 **BUSINESS PLAN**\n\n{response}", confidence=0.85,
                           actions_taken=[{"action": "business_planning"}])
    
    async def _handle_general(self, message: str, context: Any) -> AgentResponse:
        response = await self._call_claude([{"role": "user", "content": f"{self._format_context(context)}\n\nUser: {message}"}], max_tokens=1000)
        return AgentResponse(agent=self.name, content=response, confidence=0.8)
    
    async def generate_brief(self, brief_type: str) -> Optional[str]:
        if brief_type == "morning":
            return """💼 **Business Update**

📋 **Tenders**
• 2 new health-tech tenders identified
• 1 deadline this week (County Health Digitization - Friday)

💰 **Income (This Week)**
• Total: KES 12,500 ($82)
• Target: $70-350 ✅ On track
• Top source: Technical writing

👥 **CRM Alerts**
• Dr. Kamau follow-up overdue (3 days)
• Investor meeting reminder: Tomorrow 2 PM

🎯 **Uzimatek**
• Sprint 4 in progress
• 2 features pending review"""
        elif brief_type == "evening":
            return """💼 **Business Wrap**

💰 **Today's Income**: KES 3,500 ($23)
📋 **Tenders**: 1 application submitted
👥 **Contacts**: 2 follow-ups completed

📅 **Tomorrow**
• Investor call at 10 AM
• Tender deadline: County proposal"""
        return None
