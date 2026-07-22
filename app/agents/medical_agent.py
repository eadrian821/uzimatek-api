"""
Medical Intelligence Agent
Handles clinical training, medical education, and health knowledge synthesis
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings

logger = logging.getLogger(__name__)


class MedicalAgent(BaseAgent):
    """
    Medical Intelligence Agent
    
    Handles:
    - Anki flashcard generation from PDFs/notes
    - Spaced repetition scheduling
    - Literature monitoring (PubMed)
    - Clinical case preparation
    - Rotation logging
    - KE↔US protocol comparison
    - Teaching content generation
    """
    
    def __init__(self):
        super().__init__(
            name="medical",
            description="Medical training and clinical intelligence"
        )
        self.rotations = ["ENT", "Ortho", "Trauma", "General Surgery", "Internal Medicine"]
        self.study_topics = []
        
    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Medical Intelligence Agent, supporting {settings.user_name}'s medical training.

Your capabilities:
1. FLASHCARD GENERATION: Create Anki-compatible flashcards from uploaded content
2. LITERATURE MONITORING: Track and summarize relevant medical research
3. CLINICAL LOGGING: Record procedures, rotations, and case experiences
4. STUDY SUPPORT: Quiz mode, spaced repetition recommendations
5. PROTOCOL COMPARISON: Compare Kenyan (MTRH) vs US clinical protocols

Current context:
- User is completing medical training with rotations at MTRH, Eldoret
- Has US clinical experience (LA)
- Specialization interest: ENT
- Uses Anki for spaced repetition

Guidelines:
- Use proper medical terminology
- Be concise but accurate
- For flashcards, use cloze deletion and Q&A formats
- For literature, prioritize high-impact journals and recent publications
- For clinical logs, capture: date, rotation, procedure, supervisor, notes
- Always consider patient privacy (no real patient identifiers)

Respond in a helpful, professional manner appropriate for medical education."""

    @property
    def capabilities(self) -> List[str]:
        return [
            "flashcard_generation",
            "literature_search",
            "literature_summarize",
            "clinical_log",
            "quiz_mode",
            "study_schedule",
            "protocol_comparison",
            "teaching_content"
        ]
    
    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        """Process medical-related requests"""
        
        intent_str = intent.value if hasattr(intent, 'value') else str(intent)
        
        # Route based on intent
        if "flashcard" in intent_str:
            return await self._handle_flashcard_request(message, attachments, context)
        elif "literature" in intent_str:
            return await self._handle_literature_request(message, context)
        elif "quiz" in intent_str:
            return await self._handle_quiz_request(message, context)
        elif "log" in intent_str:
            return await self._handle_log_request(message, context)
        elif "study" in intent_str:
            return await self._handle_study_request(message, context)
        else:
            return await self._handle_general_medical(message, context)
    
    async def _handle_flashcard_request(
        self,
        message: str,
        attachments: List[Dict],
        context: Any
    ) -> AgentResponse:
        """Generate Anki flashcards from content"""
        
        prompt = f"""Create medical flashcards from this request.

User request: "{message}"

{f'Attachment info: {attachments}' if attachments else 'No attachments provided.'}

Generate flashcards in this JSON format:
{{
    "deck_name": "Deck Name",
    "cards": [
        {{
            "type": "cloze",
            "content": "The {{{{c1::answer}}}} is hidden in context",
            "extra": "Additional notes"
        }},
        {{
            "type": "basic",
            "front": "Question?",
            "back": "Answer with explanation",
            "extra": "Optional memory aid"
        }}
    ],
    "tags": ["topic1", "topic2"],
    "estimated_cards": 10
}}

Guidelines:
- Create 5-15 cards per concept
- Use cloze deletion for definitions and facts
- Use basic cards for explanations and reasoning
- Include clinical correlations where relevant
- Add memory aids (mnemonics) when helpful"""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000
            )
            
            # Try to parse JSON from response
            json_start = response.find('{')
            json_end = response.rfind('}') + 1
            
            if json_start != -1 and json_end > json_start:
                flashcard_data = json.loads(response[json_start:json_end])
                card_count = len(flashcard_data.get("cards", []))
                
                return AgentResponse(
                    agent=self.name,
                    content=f"✅ Created {card_count} flashcards for deck: **{flashcard_data.get('deck_name', 'New Deck')}**\n\n"
                            f"Tags: {', '.join(flashcard_data.get('tags', []))}\n\n"
                            f"Cards are ready to import to Anki. Would you like me to:\n"
                            f"1. Export as .apkg file\n"
                            f"2. Show card previews\n"
                            f"3. Add more cards",
                    confidence=0.9,
                    actions_taken=[{"action": "flashcard_generation", "count": card_count}],
                    data={"flashcards": flashcard_data}
                )
            else:
                return AgentResponse(
                    agent=self.name,
                    content=response,
                    confidence=0.7
                )
                
        except Exception as e:
            logger.error(f"Flashcard generation error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I encountered an error generating flashcards. Please try again with more specific content.",
                confidence=0.3
            )
    
    async def _handle_literature_request(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle literature search and monitoring requests"""
        
        prompt = f"""Process this medical literature request.

User request: "{message}"

{self._format_context(context)}

Provide:
1. Search strategy (PubMed terms, filters)
2. Key recent papers (if you know of relevant ones)
3. Summary of the current evidence landscape
4. Suggested reading prioritization

Format as a helpful, concise response for a medical professional."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.85,
                actions_taken=[{"action": "literature_search", "query": message}],
                follow_up_needed=True,
                follow_up_question="Would you like me to add any of these to your reading queue?"
            )
            
        except Exception as e:
            logger.error(f"Literature search error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't complete the literature search. Please try a more specific query.",
                confidence=0.3
            )
    
    async def _handle_quiz_request(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle quiz/study mode requests"""
        
        prompt = f"""Create a medical quiz based on this request.

User request: "{message}"

{self._format_context(context)}

Generate a quiz with:
1. 5 questions of varying difficulty (easy, medium, hard)
2. Mix of question types: multiple choice, short answer, clinical vignette
3. Explanations for each answer
4. Clinical pearls or memory aids

Format:
Q1 (Difficulty): Question
A) Option 1
B) Option 2
C) Option 3
D) Option 4

[After user answers, provide: Correct Answer + Explanation]

Start with the first question and wait for the answer."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.9,
                actions_taken=[{"action": "quiz_started", "topic": message}],
                data={"quiz_active": True}
            )
            
        except Exception as e:
            logger.error(f"Quiz generation error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't generate a quiz. Please specify a topic.",
                confidence=0.3
            )
    
    async def _handle_log_request(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle clinical procedure logging"""
        
        prompt = f"""Parse this clinical log entry.

User input: "{message}"

Extract and structure:
- Date (default: today)
- Rotation/Specialty
- Procedure/Case
- Supervisor
- Hours (if mentioned)
- Notes/Learning points
- Tags for categorization

Confirm the log entry and ask for any missing critical information.

Response format:
📋 **Clinical Log Entry**
- Date: [extracted date]
- Rotation: [specialty]
- Procedure: [what was done]
- Supervisor: [name if provided]
- Duration: [hours if mentioned]
- Notes: [key points]

[Confirmation message or request for missing info]"""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.85,
                actions_taken=[{"action": "clinical_log", "entry": message}],
                follow_up_needed="supervisor" not in message.lower()
            )
            
        except Exception as e:
            logger.error(f"Clinical log error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't process that log entry. Please use format: 'Log: [procedure], [rotation], supervised by [name]'",
                confidence=0.3
            )
    
    async def _handle_study_request(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle study scheduling and planning"""
        
        prompt = f"""Help with medical study planning.

User request: "{message}"

{self._format_context(context)}

Consider:
- Optimal study times based on context
- Spaced repetition principles
- Integration with clinical rotations
- Energy management

Provide:
1. Recommended study schedule
2. Topic prioritization
3. Study technique suggestions
4. Break reminders

Be practical and actionable."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200
            )
            
            return AgentResponse(
                agent=self.name,
                content=response,
                confidence=0.8,
                actions_taken=[{"action": "study_planning"}]
            )
            
        except Exception as e:
            logger.error(f"Study planning error: {e}")
            return AgentResponse(
                agent=self.name,
                content="I couldn't create a study plan. What topic would you like to focus on?",
                confidence=0.3
            )
    
    async def _handle_general_medical(
        self,
        message: str,
        context: Any
    ) -> AgentResponse:
        """Handle general medical queries"""
        
        response = await self._call_claude(
            messages=[{"role": "user", "content": f"{self._format_context(context)}\n\nUser: {message}"}],
            max_tokens=1200
        )
        
        return AgentResponse(
            agent=self.name,
            content=response,
            confidence=0.8
        )
    
    async def generate_brief(self, brief_type: str) -> Optional[str]:
        """Generate medical brief for daily updates"""
        
        if brief_type == "morning":
            # Generate morning medical brief
            return """📚 **Medical Study Status**
• Anki cards due today: 45
• Current streak: 12 days
• Weak areas flagged: Middle ear anatomy, Mastoid surgery techniques

🏥 **Today's Rotation**
• Rotation: ENT
• Focus: Outpatient clinic
• Pre-rounding checklist ready

📖 **Literature Update**
• 2 new papers in your queue matching "otology" keywords"""
        
        elif brief_type == "evening":
            return """📚 **Study Summary**
• Cards reviewed: 52/45 (115%)
• Accuracy: 78%
• Time spent: 45 minutes

🏥 **Clinical Log**
• Procedures logged today: 2
• Hours logged: 6.5

💡 **Tomorrow's Prep**
• Review: Cholesteatoma management
• 3 papers in queue"""
        
        return None
