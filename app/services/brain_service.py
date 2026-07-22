"""
Brain Service — Proactive Cross-Source Knowledge Connection Engine
Runs twice daily as background task.
Surfaces connections across Obsidian notes, OneNote, gaps, and gold-standard corpus.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from app.agents.base import BaseAgent, AgentResponse
from app.core.config import settings
from app.services.memory import memory

logger = logging.getLogger(__name__)


class BrainService(BaseAgent):
    """
    Proactive insight engine.
    
    Every 12 hours:
    1. Query all Qdrant collections simultaneously for semantic connections
    2. Surface cross-source connections: "Your OneNote annotation on X relates to your gap on Y"
    3. Generate morning brief with Anki due count + top recommendations + connections
    4. Warn if vault not synced, Anki not reviewed in >2 days
    """

    def __init__(self):
        super().__init__(name="brain", description="Proactive cross-source connection engine")

    @property
    def system_prompt(self) -> str:
        return f"""You are JARVIS's Brain Service for {settings.user_name}, a medical student at MTRH, Eldoret.

Your function: Find non-obvious connections between knowledge sources and surface them proactively.

Rules:
1. Only surface connections that are CLINICALLY MEANINGFUL — not superficial keyword matches
2. One insight must connect at least 2 different sources (e.g., OneNote annotation + Qdrant gap)
3. Be specific: name the exact mechanism or clinical fact that links them
4. Keep each insight to 2-3 sentences maximum
5. Prioritize insights that would directly improve patient care or exam performance

Format each insight as:
🧠 **Connection:** [Source A] ↔ [Source B]
_[One sentence on the shared mechanism/principle]_
💡 [Specific clinical action: e.g., "Suggest adding to Anki as: ..."]"""

    @property
    def capabilities(self) -> List[str]:
        return ["morning_brief", "knowledge_connections", "cross_source_analysis"]

    async def process(
        self,
        message: str,
        intent,
        context,
        attachments: List[Dict] = None
    ) -> AgentResponse:
        return await self.generate_morning_brief()

    async def generate_morning_brief(self) -> AgentResponse:
        """Full morning brief: Anki stats + insights + connections + health checks."""
        from app.services.anki_service import anki
        from app.services.obsidian_service import obsidian

        sections = []
        now = datetime.now()
        sections.append(f"☀️ **Good morning, {settings.user_name}** — {now.strftime('%A, %B %d')}\n")

        # 1. Anki review count
        try:
            due_info = await anki.get_due_count(settings.anki_default_deck)
            due = due_info["due"]
            new = due_info["new"]
            if due > 0 or new > 0:
                sections.append(f"🃏 **Anki** — {due} due · {new} new")
            else:
                sections.append("🃏 **Anki** — All caught up ✓")
        except Exception:
            sections.append("🃏 **Anki** — (offline)")

        # 2. Recent clinical captures
        try:
            recent_captures = await memory.episodic.get_recent(
                domain="medical", event_type="clinical_capture", days=1
            )
            if recent_captures:
                sections.append(f"\n📋 **Yesterday's captures:** {len(recent_captures)}")
                for cap in recent_captures[:2]:
                    sections.append(f"  • _{cap['content'][:80]}_")
        except Exception:
            pass

        # 3. Cross-source connections
        connections = await self._find_connections()
        if connections:
            sections.append("\n🧠 **Knowledge Connections:**")
            sections.extend(connections[:3])

        # 4. Obsidian recommendations
        try:
            recs = await obsidian.get_recommendations_from_notes(days=7)
            if recs:
                sections.append("\n💊 **From your notes:**")
                for rec in recs[:2]:
                    sections.append(f"  • _{rec[:100]}_")
        except Exception:
            pass

        # 5. Gap count from last 7 days
        try:
            recent_gaps = await memory.episodic.get_recent(domain="medical_gap", days=7)
            if recent_gaps:
                sections.append(f"\n⚡ **Recent gaps:** {len(recent_gaps)} this week")
                # Most repeated gap topic
                topics = {}
                for g in recent_gaps:
                    meta = g.get("metadata")
                    if isinstance(meta, str):
                        import json as _json
                        try:
                            meta = _json.loads(meta)
                        except Exception:
                            meta = {}
                    topic = meta.get("topic", "unknown") if meta else "unknown"
                    topics[topic] = topics.get(topic, 0) + 1
                if topics:
                    top = max(topics, key=topics.get)
                    sections.append(f"  _Most frequent gap area: **{top}** ({topics[top]}x)_")
        except Exception:
            pass

        # 6. Health checks
        health = await self._run_health_checks()
        if health:
            sections.append(f"\n⚠️ {health}")

        # 7. Daily prompt
        sections.append(f"\n---\n_Type `/recall [topic]` to start a recall session, or `/quiz` for a Socratic session._")

        content = "\n".join(sections)
        return AgentResponse(
            agent=self.name,
            content=content,
            confidence=0.95,
            actions_taken=[{"action": "morning_brief", "timestamp": now.isoformat()}]
        )

    async def _find_connections(self) -> List[str]:
        """
        Core connection engine: find cross-source semantic relationships.
        """
        connections = []
        try:
            # Get recent gaps to use as seed queries
            recent_gaps = await memory.episodic.get_recent(domain="medical_gap", days=7, limit=10)
            if not recent_gaps:
                return []

            for gap in recent_gaps[:5]:
                gap_content = gap.get("content", "")
                if not gap_content:
                    continue

                # Search across ALL collections for related content
                results = await memory.semantic.search_across_collections(
                    query=gap_content,
                    collections=["onenote_annotations", "obsidian_notes", "medical_recommendations", "clinical_captures"],
                    limit_per=2
                )

                # Find meaningful cross-source hits
                relevant_sources = {
                    col: hits
                    for col, hits in results.items()
                    if hits and hits[0].get("score", 0) > 0.55  # Only high-confidence matches
                }

                if len(relevant_sources) >= 1:
                    # Build connection insight via Claude
                    insight = await self._synthesize_connection(gap_content, relevant_sources)
                    if insight:
                        connections.append(insight)

        except Exception as e:
            logger.error(f"Connection finding error: {e}")

        return connections

    async def _synthesize_connection(
        self,
        gap_content: str,
        related_sources: Dict[str, List[Dict]]
    ) -> Optional[str]:
        """Use Claude to articulate a connection between a gap and related source material."""
        sources_text = ""
        for col, hits in related_sources.items():
            col_display = col.replace("_", " ").title()
            for hit in hits[:1]:
                sources_text += f"\n[{col_display}] {hit.get('value', '')[:200]}"

        if not sources_text:
            return None

        prompt = f"""Find the clinical connection between:

GAP: {gap_content}

RELATED MATERIAL:
{sources_text}

If there is a meaningful clinical connection, express it in 2 sentences maximum using the format:
🧠 **Connection:** [source] ↔ [gap]
_[shared mechanism]_
💡 [specific action]

If there is NO meaningful connection, respond with: NONE"""

        try:
            result = await self._call_claude(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150
            )
            if "NONE" in result or len(result) < 20:
                return None
            return result.strip()
        except Exception:
            return None

    async def _run_health_checks(self) -> str:
        """Check system health and data freshness."""
        issues = []
        from app.services.obsidian_service import obsidian

        # Check Obsidian vault freshness
        try:
            daily_notes = await obsidian.get_daily_notes(days=3)
            if not daily_notes:
                issues.append("Obsidian vault has no recent daily notes (>3 days)")
        except Exception:
            pass

        # Check Anki review streak
        try:
            from app.services.anki_service import anki
            due_info = await anki.get_due_count()
            if due_info.get("due", 0) > 50:
                issues.append(f"Anki backlog: {due_info['due']} overdue cards")
        except Exception:
            pass

        return " | ".join(issues) if issues else ""
