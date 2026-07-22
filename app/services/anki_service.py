"""
AnkiConnect Service
Direct push to local Anki via AnkiConnect addon (port 8765)
Handles card creation WITH clinical images (dual-coding)
"""

import asyncio
import base64
import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Clinical Image Fetcher — Wikimedia Commons + OpenMedical
# ─────────────────────────────────────────────────────────────────────────────

class MedicalImageFetcher:
    """Fetches clinically relevant open-access images for dual-coding."""

    # Curated search terms map for common medical topics
    TOPIC_IMAGE_HINTS = {
        "tympanic": "tympanic membrane otoscope",
        "cholesteatoma": "cholesteatoma ear pathology",
        "mastoid": "mastoid anatomy temporal bone",
        "glaucoma": "optic disc glaucoma cupping",
        "cataract": "cataract lens opacity slit lamp",
        "retina": "fundus photograph retina",
        "tonsillar": "tonsillar hypertrophy throat",
        "adenoid": "adenoid nasopharynx",
        "epistaxis": "epistaxis nasal anatomy",
        "fracture": "x-ray fracture radiograph",
        "pneumonia": "pneumonia chest xray infiltrate",
        "tb": "tuberculosis chest xray cavitation",
        "pulmonary": "pulmonary pathology lung",
        "cardiac": "cardiac anatomy heart cross-section",
        "ecg": "ecg electrocardiogram waveform",
        "caries": "dental caries tooth decay",
        "periodontitis": "periodontitis gum disease",
    }

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=15.0)
        self.commons_api = settings.wikimedia_api_url

    async def search_image(self, topic: str, card_front: str) -> Optional[Tuple[str, str]]:
        """
        Search Wikimedia Commons for a relevant clinical image.
        Returns (filename, description) or None.
        """
        # Build smart search query
        query = self._build_query(topic, card_front)
        try:
            params = {
                "action": "query",
                "generator": "search",
                "gsrsearch": f"filetype:bitmap {query}",
                "gsrnamespace": 6,  # File namespace
                "gsrlimit": 10,
                "prop": "imageinfo",
                "iiprop": "url|mediatype|mime|size",
                "iiurlwidth": 800,
                "format": "json",
                "origin": "*"
            }
            resp = await self.client.get(self.commons_api, params=params)
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            for page in pages.values():
                info = page.get("imageinfo", [{}])[0]
                mime = info.get("mime", "")
                url = info.get("thumburl") or info.get("url", "")
                size = info.get("size", 0)
                # Filter: only reasonable sized images, no SVG for compatibility
                if mime.startswith("image/") and "svg" not in mime and size < 5_000_000 and url:
                    title = page.get("title", "").replace("File:", "")
                    logger.info(f"Found image for '{query}': {title}")
                    return url, title

            # Fallback: try NIH/NLM open access
            return await self._search_nlm(query)

        except Exception as e:
            logger.warning(f"Image search failed for '{query}': {e}")
            return None

    async def download_image_for_anki(self, url: str, filename: str) -> Optional[str]:
        """
        Download image and save to Anki media folder.
        Returns the Anki-safe filename to use in card HTML.
        """
        try:
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return None
            # Create safe filename
            safe_name = re.sub(r'[^\w\-.]', '_', filename)[:100]
            if not any(safe_name.endswith(ext) for ext in ['.jpg', '.png', '.gif', '.webp']):
                safe_name += '.jpg'
            anki_path = Path(settings.anki_image_path) / safe_name
            anki_path.write_bytes(resp.content)
            logger.info(f"Saved image to Anki media: {safe_name}")
            return safe_name
        except Exception as e:
            logger.error(f"Image download error: {e}")
            return None

    async def get_image_for_card(self, topic: str, card_content: str) -> Optional[str]:
        """
        Complete pipeline: search → download → return Anki filename.
        Returns Anki HTML img tag or None.
        """
        result = await self.search_image(topic, card_content)
        if not result:
            return None
        url, description = result
        filename = f"jarvis_{hashlib.md5(url.encode()).hexdigest()[:8]}_{description[:30]}"
        anki_file = await self.download_image_for_anki(url, filename)
        if anki_file:
            return f'<img src="{anki_file}" style="max-width:400px; border-radius:8px;" alt="{description}"><br><small style="color:#888">{description}</small>'
        return None

    async def _search_nlm(self, query: str) -> Optional[Tuple[str, str]]:
        """Fallback: search NCBI/NLM for open-access medical images."""
        try:
            resp = await self.client.get(
                "https://openi.nlm.nih.gov/api/search",
                params={"query": query, "ctype": "xray,mri,ct,photo", "nResults": 5}
            )
            data = resp.json()
            images = data.get("list", [])
            if images:
                img = images[0]
                url = img.get("imgLarge") or img.get("imgThumb")
                caption = img.get("IUCRCode", query)
                if url:
                    return url, caption
        except Exception:
            pass
        return None

    def _build_query(self, topic: str, card_content: str) -> str:
        topic_lower = topic.lower()
        for key, hint in self.TOPIC_IMAGE_HINTS.items():
            if key in topic_lower or key in card_content.lower():
                return hint
        # Fallback: extract key medical terms from card content
        words = re.findall(r'\b[A-Za-z]{5,}\b', card_content)[:5]
        return f"medical anatomy {topic} " + " ".join(words[:3])


image_fetcher = MedicalImageFetcher()


# ─────────────────────────────────────────────────────────────────────────────
# AnkiConnect Client
# ─────────────────────────────────────────────────────────────────────────────

class AnkiConnectService:
    """
    Direct interface to local Anki via AnkiConnect addon.
    AnkiConnect must be installed in Anki (addon code: 2055492159).
    """

    def __init__(self):
        self.url = settings.ankiconnect_url
        self.client = httpx.AsyncClient(timeout=30.0)
        self.version = 6

    async def _request(self, action: str, **params) -> Any:
        """Send a request to AnkiConnect."""
        payload = {"action": action, "version": self.version, "params": params}
        try:
            resp = await self.client.post(self.url, json=payload)
            result = resp.json()
            if result.get("error"):
                raise RuntimeError(f"AnkiConnect error: {result['error']}")
            return result.get("result")
        except httpx.ConnectError:
            raise RuntimeError("AnkiConnect not reachable. Make sure Anki is open with the AnkiConnect addon installed.")
        except Exception as e:
            raise RuntimeError(f"AnkiConnect request failed: {e}")

    async def is_available(self) -> bool:
        """Check if AnkiConnect is running."""
        try:
            await self._request("version")
            return True
        except Exception:
            return False

    async def ensure_deck(self, deck_name: str):
        """Create deck hierarchy if it doesn't exist."""
        await self._request("createDeck", deck=deck_name)

    async def ensure_note_type(self, model_name: str = "JARVIS Medical") -> bool:
        """Create custom note type with image support if not exists."""
        existing = await self._request("modelNames")
        if model_name in existing:
            return True
        await self._request(
            "createModel",
            modelName=model_name,
            inOrderFields=["Front", "Back", "Image", "Extra", "Source", "Tags"],
            css="""
.card { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 16px;
        max-width: 700px; margin: 0 auto; padding: 20px; }
.front { font-weight: bold; font-size: 18px; color: #1a1a2e; }
.back { color: #16213e; line-height: 1.6; }
.image-wrap { text-align: center; margin: 15px 0; }
.extra { color: #888; font-size: 13px; margin-top: 10px; border-top: 1px solid #eee; padding-top: 8px; }
.source { color: #aaa; font-size: 11px; }
img { max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); }
            """,
            cardTemplates=[
                {
                    "Name": "JARVIS Basic",
                    "Front": "{{Front}}",
                    "Back": """{{FrontSide}}<hr id="answer">
<div class="back">{{Back}}</div>
<div class="image-wrap">{{Image}}</div>
<div class="extra">{{Extra}}</div>
<div class="source">📚 {{Source}}</div>"""
                }
            ]
        )
        logger.info(f"Created note type: {model_name}")
        return True

    async def add_note(
        self,
        deck: str,
        front: str,
        back: str,
        tags: List[str] = None,
        image_html: str = "",
        extra: str = "",
        source: str = "JARVIS",
        model: str = "JARVIS Medical",
        allow_duplicate: bool = False
    ) -> Optional[int]:
        """Add a basic note to Anki."""
        await self.ensure_deck(deck)
        await self.ensure_note_type(model)
        note = {
            "deckName": deck,
            "modelName": model,
            "fields": {
                "Front": front,
                "Back": back,
                "Image": image_html or "",
                "Extra": extra,
                "Source": source,
                "Tags": " ".join(tags or [])
            },
            "options": {
                "allowDuplicate": allow_duplicate,
                "duplicateScope": "deck"
            },
            "tags": tags or []
        }
        try:
            note_id = await self._request("addNote", note=note)
            logger.info(f"Added Anki card: {front[:50]}... → deck {deck}")
            return note_id
        except Exception as e:
            logger.error(f"Add note error: {e}")
            return None

    async def add_cloze_note(
        self,
        deck: str,
        text: str,
        tags: List[str] = None,
        image_html: str = "",
        back_extra: str = "",
        source: str = "JARVIS"
    ) -> Optional[int]:
        """Add a cloze deletion note."""
        await self.ensure_deck(deck)
        existing_cloze = await self._request("modelNames")
        cloze_model = "Cloze" if "Cloze" in existing_cloze else "Basic"
        note = {
            "deckName": deck,
            "modelName": cloze_model,
            "fields": {
                "Text": text + (f"<br><br>{image_html}" if image_html else ""),
                "Extra": back_extra or source
            },
            "options": {"allowDuplicate": False},
            "tags": tags or []
        }
        try:
            note_id = await self._request("addNote", note=note)
            return note_id
        except Exception as e:
            logger.error(f"Cloze note error: {e}")
            return None

    async def add_batch(self, notes: List[Dict]) -> Tuple[int, int]:
        """Add multiple notes. Returns (success_count, fail_count)."""
        success = fail = 0
        for n in notes:
            note_type = n.get("type", "basic")
            if note_type == "cloze":
                result = await self.add_cloze_note(
                    deck=n["deck"],
                    text=n["content"],
                    tags=n.get("tags", []),
                    image_html=n.get("image_html", ""),
                    back_extra=n.get("extra", ""),
                    source=n.get("source", "JARVIS")
                )
            else:
                result = await self.add_note(
                    deck=n["deck"],
                    front=n["front"],
                    back=n["back"],
                    tags=n.get("tags", []),
                    image_html=n.get("image_html", ""),
                    extra=n.get("extra", ""),
                    source=n.get("source", "JARVIS")
                )
            if result:
                success += 1
            else:
                fail += 1
            await asyncio.sleep(0.05)  # Small delay to not overwhelm AnkiConnect
        return success, fail

    async def get_due_count(self, deck: str = None) -> Dict[str, int]:
        """Get count of due cards for morning brief."""
        try:
            query = f"deck:{deck} is:due" if deck else "is:due"
            card_ids = await self._request("findCards", query=query)
            new_query = f"deck:{deck} is:new" if deck else "is:new"
            new_ids = await self._request("findCards", query=new_query)
            return {"due": len(card_ids or []), "new": len(new_ids or [])}
        except Exception as e:
            logger.warning(f"Due count error: {e}")
            return {"due": 0, "new": 0}

    async def sync(self):
        """Trigger Anki sync (if AnkiWeb account configured)."""
        try:
            await self._request("sync")
            logger.info("Anki sync triggered")
        except Exception as e:
            logger.warning(f"Anki sync error (non-fatal): {e}")

    async def create_deck_snapshot(self, source_deck: str, snapshot_name: str):
        """Clone a deck as a snapshot (for rotation-end crucible)."""
        try:
            # Get all note IDs in source deck
            note_ids = await self._request("findNotes", query=f"deck:{source_deck}")
            notes_info = await self._request("notesInfo", notes=note_ids)
            await self.ensure_deck(snapshot_name)
            # This is a reference snapshot — just tag all cards with the snapshot name
            safe_tag = snapshot_name.replace(" ", "_").replace("::", "_")
            if note_ids:
                await self._request("addTags", notes=note_ids, tags=f"snapshot::{safe_tag}")
            logger.info(f"Deck snapshot created: {snapshot_name}")
        except Exception as e:
            logger.error(f"Deck snapshot error: {e}")


# Global instance
anki = AnkiConnectService()
