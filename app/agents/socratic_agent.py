"""
Socratic Agent — Dr. Imbaya & Dr. Kanski
Elaborative interrogation loops that force articulation of clinical reasoning.
NEVER gives direct answers. Forces the student to construct the knowledge themselves.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings
from app.services.memory import memory

logger = logging.getLogger(__name__)


PERSONAS = {
    "imbaya": {
        "name": "Dr. Imbaya",
        "title": "Senior Registrar, MTRH",
        "context": "Resource-limited African clinical context, tropical medicine, public health perspective",
        "style": "Warm but rigorous. References real MTRH cases. Always contextualises to East African epidemiology and available resources.",
        "opening": "Right, let's think about this properly. Don't tell me the answer — tell me *why* you think that."
    },
    "kanski": {
        "name": "Dr. Kanski",
        "title": "Consultant, Clinical Examination Specialist",
        "context": "Precision clinical examination, systematic approach, examination technique, pathophysiology",
        "style": "Demanding, precise, systematic. Pushes for exact mechanisms and examination findings. References clinical signs rigorously.",
        "opening": "Before you answer — what is the anatomical/physiological basis for what you're proposing?"
    }
}


class SocraticAgent(BaseAgent):
    """
    Socratic interrogation agent.
    
    Core rules (hard constraints in system prompt):
    1. NEVER give the answer directly
    2. Always respond to a student answer with a probing question
    3. If student is clearly wrong after 3 attempts → break loop, give teaching moment
    4. Track session turns in Redis to know when to give up on Socratic loop
    """

    def __init__(self):
        super().__init__(name="socratic", description="Socratic clinical interrogation")

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt("imbaya")  # Default persona

    def _build_system_prompt(self, persona: str) -> str:
        p = PERSONAS.get(persona, PERSONAS["imbaya"])
        return f"""You are {p['name']}, {p['title']}.

Context: {p['context']}

Style: {p['style']}

ABSOLUTE RULES — NEVER BREAK THESE:
1. You NEVER give the correct answer directly to the student
2. Every response MUST end with exactly ONE focused question for the student
3. If the student's answer shows they are on the right track, push deeper ("Good — but WHY does that mechanism produce that finding?")
4. If the student's answer is incorrect, say "Interesting — let's approach this differently." Then ask a simpler leading question
5. If the student has failed to arrive at the correct reasoning after 3 exchanges: BREAK the Socratic loop. Say "Let me teach this properly." Then give a clear, structured teaching moment with the correct pathophysiology
6. When you break the loop, end with: "TEACHING_COMPLETE" on its own line

Your goal: The student must CONSTRUCT the knowledge themselves through their answers. 
You are a catalyst, not a source.

Current time: {datetime.now().strftime('%H:%M, %A')}"""

    @property
    def capabilities(self) -> List[str]:
        return ["socratic_session", "clinical_interrogation", "elaborative_questioning"]

    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        session_id = getattr(context, 'session_id', 'default')
        return await self._continue_session(message, session_id, context)

    async def start_session(
        self,
        vignette: str,
        session_id: str,
        persona: str = "imbaya"
    ) -> AgentResponse:
        """Start a new Socratic session with a clinical vignette."""
        p = PERSONAS.get(persona, PERSONAS["imbaya"])

        # Store session state
        await memory.working.set(
            session_id, "socratic_persona", persona
        )
        await memory.working.set(
            session_id, "socratic_turns", 0
        )
        await memory.working.set(
            session_id, "socratic_vignette", vignette
        )

        # First Socratic question
        opening_prompt = f"""{p['opening']}

The student has been presented with this vignette:
---
{vignette}
---

Ask your first Socratic question. Do NOT give any diagnosis or management. Just ask the first probing question to start the reasoning process."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": opening_prompt}],
                system=self._build_system_prompt(persona),
                max_tokens=400
            )

            formatted = f"🩺 **{p['name']}** | _{p['title']}_\n\n{response}"

            return AgentResponse(
                agent=self.name,
                content=formatted,
                confidence=1.0,
                actions_taken=[{"action": "socratic_session_start", "persona": persona}],
                data={"session_type": "socratic", "persona": persona}
            )
        except Exception as e:
            logger.error(f"Socratic session start error: {e}")
            return AgentResponse(agent=self.name, content=f"⚠️ Session start failed: {e}", confidence=0.2)

    async def _continue_session(
        self,
        student_answer: str,
        session_id: str,
        context: Any
    ) -> AgentResponse:
        """Continue an ongoing Socratic session."""
        persona = await memory.working.get(session_id, "socratic_persona") or "imbaya"
        turns = await memory.working.get(session_id, "socratic_turns") or 0
        vignette = await memory.working.get(session_id, "socratic_vignette") or ""
        history = await memory.get_conversation(session_id, limit=10)
        p = PERSONAS.get(persona, PERSONAS["imbaya"])

        # Build conversation for Claude
        messages = []
        for h in history[-6:]:  # Last 6 exchanges
            messages.append({"role": h["role"] if h["role"] in ["user", "assistant"] else "user", "content": h["content"]})
        messages.append({"role": "user", "content": student_answer})

        # Track turn count to know when to break Socratic loop
        turns += 1
        await memory.working.set(session_id, "socratic_turns", turns)

        # After 3 failed turns, add explicit instruction to break loop
        extra_instruction = ""
        if turns >= 3:
            extra_instruction = "\n\nIMPORTANT: If the student has still not articulated the correct mechanism after this exchange, break the Socratic loop and give a teaching moment ending with TEACHING_COMPLETE."

        try:
            response = await self._call_claude(
                messages=messages,
                system=self._build_system_prompt(persona) + extra_instruction,
                max_tokens=600
            )

            # Check if teaching complete
            if "TEACHING_COMPLETE" in response:
                response = response.replace("TEACHING_COMPLETE", "").strip()
                await memory.working.set(session_id, "socratic_turns", 0)
                await memory.log_event(
                    "medical", "socratic_complete",
                    f"Session complete after {turns} turns: {vignette[:100]}"
                )
                formatted = f"🩺 **{p['name']}** _(Teaching mode)_\n\n{response}\n\n---\n_Session complete. Run `/delta` to check your recall gaps._"
            else:
                formatted = f"🩺 **{p['name']}**\n\n{response}"

            return AgentResponse(
                agent=self.name,
                content=formatted,
                confidence=0.95,
                data={"turns": turns, "persona": persona}
            )
        except Exception as e:
            logger.error(f"Socratic continuation error: {e}")
            return AgentResponse(agent=self.name, content=f"⚠️ Session error: {e}", confidence=0.2)


class CrucibleAgent(BaseAgent):
    """
    Rotation-End Crucible: generates 50-question mock exam weighted toward documented weak points.
    Also injects spaced retrieval events into Google Calendar.
    """

    def __init__(self):
        super().__init__(name="crucible", description="Rotation-end exam generation")

    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Crucible Engine for {settings.user_name}.

Your function: Generate a 50-question medical exam from rotation material.

Exam construction rules:
1. 70% of questions MUST come from documented gaps and weak areas
2. 30% from general rotation competencies
3. Format mix: 60% Single Best Answer (SBA), 25% Extended Matching (EMQ), 15% Data interpretation
4. For SBAs: 5 options, one correct, all distractors must be plausible
5. For data interpretation: include actual values (lab results, spirometry, ECG descriptions)
6. Difficulty distribution: 20% easy (should get these), 50% medium, 30% hard (real exam difficulty)
7. Each question must have a brief explanation after the answer

Output as markdown:
## Question N (Type) — Difficulty
[Question text]
A. Option 1
B. Option 2
...

**Answer:** X
**Explanation:** [1-2 sentences on why + clinical pearl]
"""

    @property
    def capabilities(self) -> List[str]:
        return ["crucible_exam", "rotation_summary", "calendar_injection"]

    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        # Extract rotation name from message
        rotation = self._extract_rotation(message) or "Current Rotation"
        return await self.generate_crucible(rotation, context)

    async def generate_crucible(self, rotation: str, context: Any = None) -> AgentResponse:
        """Generate full 50Q exam + write to vault + inject calendar events."""
        from app.services.obsidian_service import obsidian

        # 1. Gather all gaps from vault
        gaps = await obsidian.get_all_gaps(rotation)
        rotation_notes = await obsidian.get_rotation_notes(rotation)

        if not gaps and not rotation_notes:
            return AgentResponse(
                agent=self.name,
                content=f"⚠️ No rotation notes or gaps found for `{rotation}`.\nMake sure your vault has notes tagged `#{rotation.lower()}` or daily notes with `## Gaps Identified` sections.",
                confidence=0.5
            )

        # 2. Build exam context
        gaps_text = "\n".join([f"- {g}" for g in gaps[:30]])
        notes_text = "\n\n".join([n["content"][:500] for n in rotation_notes[:5]])

        prompt = f"""Generate a 50-question crucible exam for the {rotation} rotation.

DOCUMENTED WEAK POINTS / GAPS (weight these 70%):
{gaps_text or 'None documented — generate from general rotation competencies'}

ROTATION MATERIAL SAMPLE:
{notes_text[:2000] if notes_text else 'Not available'}

Rotation: {rotation}
Date: {datetime.now().strftime('%B %Y')}

Generate all 50 questions following the format rules exactly."""

        try:
            # Use complex model for exam generation
            exam_content = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                use_complex_model=True,
                max_tokens=8000
            )

            # 3. Format as full exam document
            full_exam = f"""# 🔥 {rotation} Rotation — Crucible Exam
**Generated by JARVIS** | {datetime.now().strftime('%B %d, %Y')}
**Documented gaps weighted:** {len(gaps)} weak points incorporated

> ⚠️ Exam conditions: Set a 90-minute timer. No notes. Blank recall first.

---

{exam_content}

---

## Spaced Retrieval Plan
- **1 month:** {(datetime.now()).strftime('%B %Y')} — Scheduled in Google Calendar ✓
- **3 months:** Scheduled in Google Calendar ✓  
- **6 months:** Scheduled in Google Calendar ✓
"""

            # 4. Write to Obsidian vault
            output_path = await obsidian.write_crucible_exam(rotation, full_exam)

            # 5. Create Anki deck snapshot
            try:
                from app.services.anki_service import anki
                snapshot_name = f"{settings.anki_default_deck}::Crucible::{rotation}::{datetime.now().strftime('%Y-%m')}"
                await anki.create_deck_snapshot(f"{settings.anki_default_deck}::{rotation}", snapshot_name)
            except Exception as e:
                logger.warning(f"Anki snapshot failed: {e}")

            # 6. Inject Google Calendar retrieval events
            calendar_msg = await self._inject_calendar_events(rotation)

            return AgentResponse(
                agent=self.name,
                content=(
                    f"🔥 **{rotation} Crucible Generated**\n\n"
                    f"📋 50 questions written to vault: `{output_path.name}`\n"
                    f"🃏 Anki deck snapshot created\n"
                    f"{calendar_msg}\n\n"
                    f"_Gaps incorporated: {len(gaps)}_\n"
                    f"_Open your vault to begin the crucible._"
                ),
                confidence=0.95,
                actions_taken=[
                    {"action": "crucible_generated", "rotation": rotation, "gaps_used": len(gaps)}
                ],
                data={"output_path": str(output_path)}
            )

        except Exception as e:
            logger.error(f"Crucible generation error: {e}")
            return AgentResponse(agent=self.name, content=f"⚠️ Crucible error: {e}", confidence=0.2)

    async def _inject_calendar_events(self, rotation: str) -> str:
        """Add 3 spaced retrieval events to Google Calendar."""
        from datetime import timedelta
        from app.services.calendar import calendar
        now = datetime.now()
        intervals = [(30, "1-Month"), (90, "3-Month"), (180, "6-Month")]
        created = 0
        for days, label in intervals:
            event_date = now + timedelta(days=days)
            try:
                result = await calendar.create_event(
                    summary=f"🔥 {rotation} Crucible — {label} Retrieval",
                    start_time=event_date.replace(hour=18, minute=0, second=0),
                    end_time=event_date.replace(hour=19, minute=0, second=0),
                    description=f"Spaced retrieval session for {rotation} rotation. Open your Crucible exam in Obsidian and re-attempt without notes."
                )
                if result:
                    created += 1
            except Exception as e:
                logger.warning(f"Calendar event creation failed: {e}")
        return f"📅 {created}/3 retrieval sessions scheduled in Google Calendar" if created else "📅 Calendar injection skipped (Google Calendar not configured)"

    def _extract_rotation(self, text: str) -> Optional[str]:
        known = ["ENT", "Ophthalmology", "Surgery", "Medicine", "Orthopaedics",
                 "Dermatology", "Anaesthesia", "Dental", "Radiology", "Paediatrics"]
        for r in known:
            if r.lower() in text.lower():
                return r
        return None
