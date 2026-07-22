"""
Delta Agent — Recall vs Gold Standard Gap Analysis
The cognitive engine at the heart of the framework.
Compares free recall against RAG-indexed textbooks and surfaces ONLY gaps.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings
from app.services.memory import memory

logger = logging.getLogger(__name__)


class DeltaAgent(BaseAgent):
    """
    Delta Engine: blank-page recall → gap identification.
    
    System design principle: The agent is instructed NEVER to summarize
    what the student got right. It only highlights gaps — the delta between
    what was recalled and what the gold standard contains.
    """

    def __init__(self):
        super().__init__(name="delta", description="Recall vs gold-standard gap analysis")

    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Delta Analysis Engine for {settings.user_name}, a medical student at MTRH, Eldoret.

YOUR CORE RULE: You NEVER summarize what the student got correct. You ONLY identify gaps.

Your function:
1. Receive the student's free recall (what they remembered about a clinical topic)
2. Compare against the gold-standard passages provided to you from textbooks
3. Output ONLY: facts missing from recall, incorrect mechanisms, missed management steps, omitted drug dosages, absent differentials

Output format (strict):
Gap :: [Specific missing fact or mechanism]
Gap :: [Another gap]

After listing gaps, end with:
SUMMARY: [One sentence: total gaps found, and the single most clinically dangerous gap]
ANKI_READY: yes

Forbidden outputs:
- Do NOT say "you correctly recalled..."
- Do NOT summarize what was right
- Do NOT give general feedback
- Do NOT explain what the gaps mean (the student will learn by looking them up)
"""

    @property
    def capabilities(self) -> List[str]:
        return ["recall_analysis", "gap_identification", "delta_generation"]

    async def process(
        self,
        message: str,
        intent: Any,
        context: Any,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        return await self._analyze_recall(message, context)

    async def analyze_recall(self, recall_text: str, topic: str = None) -> AgentResponse:
        """Public method — analyze a free recall text against gold standard."""
        return await self._analyze_recall(recall_text, topic=topic)

    async def _analyze_recall(self, recall_text: str, context: Any = None, topic: str = None) -> AgentResponse:
        """Core delta analysis pipeline."""
        # 1. Extract topic from recall if not provided
        if not topic:
            topic = await self._extract_topic(recall_text)

        # 2. Retrieve gold-standard passages from Qdrant
        gold_passages = await memory.rag_search_gold_standard(
            query=f"{topic} management diagnosis pathophysiology",
            limit=8
        )

        if not gold_passages:
            # Try broader search
            gold_passages = await memory.rag_search_gold_standard(query=recall_text[:200], limit=6)

        if not gold_passages:
            return AgentResponse(
                agent=self.name,
                content=(
                    "⚠️ No gold-standard passages found for this topic in the corpus.\n"
                    "Run `/bootstrap` to index your medical textbooks, or specify the topic more clearly.\n"
                    f"Topic detected: `{topic}`"
                ),
                confidence=0.3
            )

        # 3. Format gold standard for prompt
        gold_text = "\n\n---\n\n".join([
            f"[Source: {p.get('source_file', 'Textbook')} | {p.get('specialty', 'medicine')}]\n{p['value']}"
            for p in gold_passages
        ])

        # 4. Run delta analysis with Claude
        prompt = f"""STUDENT FREE RECALL:
---
{recall_text}
---

GOLD STANDARD PASSAGES (from indexed textbooks):
---
{gold_text}
---

Topic: {topic}

Analyze the gaps. Remember: output ONLY gaps in the format specified. No praise, no summaries of correct items."""

        try:
            response = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                use_complex_model=False,  # Sonnet is sufficient for gap analysis
                max_tokens=2000
            )

            # 5. Parse gaps from response
            gaps = self._parse_gaps(response)

            # 6. Store gaps in memory for Anki atomization and BrainService
            for gap in gaps:
                await memory.log_gap(gap, topic=topic, rotation=self._detect_rotation(recall_text))

            # 7. Write gaps to Obsidian vault
            try:
                from app.services.obsidian_service import obsidian
                for gap in gaps:
                    await obsidian.append_gap_delta(gap, topic)
            except Exception as e:
                logger.warning(f"Obsidian write failed: {e}")

            # 8. Format response
            gap_count = len(gaps)
            formatted = f"⚡ **Delta Analysis — {topic}**\n"
            formatted += f"_{gap_count} gap{'s' if gap_count != 1 else ''} found in your recall_\n\n"
            formatted += response
            if gap_count > 0:
                formatted += f"\n\n---\n💡 *Run `/anki {topic}` to atomize these gaps into Anki cards immediately.*"

            return AgentResponse(
                agent=self.name,
                content=formatted,
                confidence=0.92,
                actions_taken=[
                    {"action": "delta_analysis", "topic": topic, "gaps_found": gap_count}
                ],
                data={"gaps": gaps, "topic": topic, "gold_sources": [p.get('source_file') for p in gold_passages]},
                follow_up_needed=gap_count > 0,
                follow_up_question=f"Would you like me to push these {gap_count} gaps to Anki as cards right now?"
            )

        except Exception as e:
            logger.error(f"Delta analysis error: {e}")
            return AgentResponse(
                agent=self.name,
                content=f"⚠️ Delta analysis failed: {e}",
                confidence=0.2
            )

    def _parse_gaps(self, response: str) -> List[str]:
        """Extract gap lines from Claude response."""
        gaps = []
        for line in response.split('\n'):
            line = line.strip()
            if line.startswith("Gap ::"):
                gap_text = line.replace("Gap ::", "").strip()
                if gap_text:
                    gaps.append(gap_text)
            elif " :: " in line and not line.startswith("SUMMARY") and not line.startswith("ANKI"):
                # Flexible parsing
                parts = line.split(" :: ", 1)
                if len(parts) == 2 and len(parts[1]) > 10:
                    gaps.append(parts[1].strip())
        return gaps

    async def _extract_topic(self, text: str) -> str:
        """Use Claude to extract the medical topic from recall text."""
        try:
            result = await self._call_claude(
                messages=[{
                    "role": "user",
                    "content": f"In 3-5 words, what medical topic does this text primarily cover? Text: {text[:500]}\nRespond with ONLY the topic name, nothing else."
                }],
                max_tokens=30
            )
            return result.strip()
        except Exception:
            # Fallback: use first medical term
            words = text.split()[:20]
            return " ".join(words[:4])

    def _detect_rotation(self, text: str) -> str:
        """Try to detect which rotation this recall is from."""
        rotation_keywords = {
            "ENT": ["ear", "nose", "throat", "tonsil", "hearing", "cholesteatoma", "mastoid"],
            "Ophthalmology": ["eye", "retina", "glaucoma", "cataract", "vision", "fundus"],
            "Surgery": ["operation", "laparotomy", "hernio", "appendix", "incision"],
            "Medicine": ["pneumonia", "cardiac", "diabetes", "hypertension", "renal"],
            "Orthopaedics": ["fracture", "bone", "joint", "arthritis", "fixation"],
            "Dermatology": ["skin", "rash", "dermatitis", "psoriasis"],
            "Anaesthesia": ["anaesthesia", "intubation", "sedation", "airway"],
            "Dental": ["tooth", "dental", "caries", "periodontal", "gingival"],
        }
        text_lower = text.lower()
        for rotation, keywords in rotation_keywords.items():
            if any(kw in text_lower for kw in keywords):
                return rotation
        return "General"
