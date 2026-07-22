"""
Obsidian Service
Manages read/write to the local Obsidian vault
Vault path: C:\\Users\\eadri\\Desktop\\Dental\\MyVault
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict

import aiofiles
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent

from app.core.config import settings

logger = logging.getLogger(__name__)

VAULT = Path(settings.obsidian_vault_path)


class VaultEventHandler(FileSystemEventHandler):
    """Watchdog handler — triggers ingestion when vault files change."""

    def __init__(self, callback):
        self.callback = callback
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self.callback(Path(event.src_path), "modified"),
                    self._loop
                )

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.md'):
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(
                    self.callback(Path(event.src_path), "created"),
                    self._loop
                )


class ObsidianService:
    """Bidirectional interface to the Obsidian vault."""

    def __init__(self):
        self.vault = VAULT
        self._observer: Optional[Observer] = None
        self._ingestion_callback = None
        self._recent_writes: set = set()  # Prevent re-processing files we just wrote

    def set_ingestion_callback(self, callback):
        """Set callback for when vault files change (triggers RAG re-indexing)."""
        self._ingestion_callback = callback

    def start_watching(self, loop):
        """Start watchdog observer on the vault."""
        if self._observer:
            return
        handler = VaultEventHandler(self._on_vault_change)
        handler.set_loop(loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.vault), recursive=True)
        self._observer.start()
        logger.info(f"Watching Obsidian vault: {self.vault}")

    def stop_watching(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    async def _on_vault_change(self, path: Path, event_type: str):
        """Called by watchdog when a vault file changes."""
        # Skip files we just wrote to avoid loops
        if str(path) in self._recent_writes:
            self._recent_writes.discard(str(path))
            return
        logger.info(f"Vault change detected: {path.name} ({event_type})")
        if self._ingestion_callback:
            await self._ingestion_callback(path, event_type)

    # ─── Daily Note Management ───────────────────────────────────────────────

    def _get_daily_note_path(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.vault / f"Daily Notes/{today}.md"

    async def append_clinical_capture(self, text: str, timestamp: str = None):
        """Append a ward round clinical capture to today's Daily Note."""
        note_path = self._get_daily_note_path()
        note_path.parent.mkdir(parents=True, exist_ok=True)
        ts = timestamp or datetime.now().strftime("%H:%M")
        entry = f"\n> [!clinical] {ts} — {text}\n"
        # Ensure #clinical-capture section exists
        await self._ensure_section(note_path, "## Clinical Captures", entry)
        logger.info(f"Clinical capture appended to daily note: {text[:60]}")

    async def append_gap_delta(self, gap_text: str, topic: str):
        """Write Delta Engine output to today's Daily Note."""
        note_path = self._get_daily_note_path()
        note_path.parent.mkdir(parents=True, exist_ok=True)
        entry = f"\n- ❌ **Gap** `{topic}`: {gap_text}\n"
        await self._ensure_section(note_path, "## Gaps Identified", entry)

    async def write_delta_to_note(self, note_path: Path, gaps: List[str]):
        """Write a list of gaps to a specific note file."""
        self._recent_writes.add(str(note_path))
        async with aiofiles.open(note_path, 'a', encoding='utf-8') as f:
            await f.write("\n\n---\n## ⚡ JARVIS Delta Analysis\n")
            await f.write(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n")
            for gap in gaps:
                await f.write(f"- ❌ {gap}\n")
            await f.write("\n")

    async def write_crucible_exam(self, rotation: str, questions: str) -> Path:
        """Write rotation-end 50Q crucible exam to vault."""
        filename = f"Crucible_{rotation}_{datetime.now().strftime('%Y-%m')}.md"
        output_path = self.vault / f"Crucible/{filename}"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._recent_writes.add(str(output_path))
        async with aiofiles.open(output_path, 'w', encoding='utf-8') as f:
            await f.write(questions)
        logger.info(f"Crucible exam written: {output_path}")
        return output_path

    # ─── Note Reading ────────────────────────────────────────────────────────

    async def read_note(self, path: Path) -> Optional[str]:
        """Read a markdown note."""
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                return await f.read()
        except Exception as e:
            logger.error(f"Error reading note {path}: {e}")
            return None

    async def get_rotation_notes(self, rotation: str) -> List[Dict]:
        """Get all notes tagged with a rotation name."""
        rotation_tag = rotation.lower().replace(" ", "_")
        results = []
        for md_file in self.vault.rglob("*.md"):
            try:
                content = await self.read_note(md_file)
                if content and (f"#{rotation_tag}" in content.lower() or rotation.lower() in md_file.name.lower()):
                    results.append({
                        "path": str(md_file),
                        "name": md_file.stem,
                        "content": content
                    })
            except Exception:
                continue
        return results

    async def get_all_gaps(self, rotation: str = None) -> List[str]:
        """Scrape all '## Gaps Identified' sections from vault."""
        gaps = []
        search_path = self.vault
        for md_file in search_path.rglob("*.md"):
            try:
                content = await self.read_note(md_file)
                if not content:
                    continue
                if rotation and rotation.lower() not in content.lower() and rotation.lower() not in md_file.name.lower():
                    continue
                # Extract gaps section
                match = re.search(r'## Gaps Identified\n(.*?)(?=\n##|\Z)', content, re.DOTALL)
                if match:
                    section = match.group(1)
                    for line in section.split('\n'):
                        line = line.strip().lstrip('- ❌').strip()
                        if line and len(line) > 10:
                            gaps.append(line)
            except Exception:
                continue
        return gaps

    async def get_daily_notes(self, days: int = 7) -> List[Dict]:
        """Get content from recent daily notes."""
        daily_dir = self.vault / "Daily Notes"
        if not daily_dir.exists():
            return []
        notes = []
        for md_file in sorted(daily_dir.glob("*.md"), reverse=True)[:days]:
            content = await self.read_note(md_file)
            if content:
                notes.append({"date": md_file.stem, "content": content, "path": str(md_file)})
        return notes

    # ─── Helpers ─────────────────────────────────────────────────────────────

    async def _ensure_section(self, path: Path, heading: str, content: str):
        """Ensure a section exists in a note and append content to it."""
        self._recent_writes.add(str(path))
        if path.exists():
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                existing = await f.read()
        else:
            existing = f"# Daily Note — {datetime.now().strftime('%A, %B %d, %Y')}\n\n"

        if heading not in existing:
            existing += f"\n{heading}\n"

        # Insert content after the heading
        existing = existing.replace(heading, f"{heading}{content}", 1)

        async with aiofiles.open(path, 'w', encoding='utf-8') as f:
            await f.write(existing)

    async def get_recommendations_from_notes(self, days: int = 7) -> List[str]:
        """
        Extract #recommendation or #interesting tagged content from recent notes.
        Used by BrainService for morning brief.
        """
        recommendations = []
        recent = await self.get_daily_notes(days)
        for note in recent:
            content = note["content"]
            # Look for lines with #recommendation or #interesting tags
            for line in content.split('\n'):
                if '#recommendation' in line or '#interesting' in line or '#therapy' in line:
                    clean = re.sub(r'#\w+', '', line).strip().lstrip('- >').strip()
                    if len(clean) > 15:
                        recommendations.append(clean)
        return recommendations[:5]  # Top 5 most recent


# Global instance
obsidian = ObsidianService()
