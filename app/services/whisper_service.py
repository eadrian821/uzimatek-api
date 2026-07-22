"""
Whisper Service
Audio → text pipeline for Galaxy Watch/Buds voice captures
Watches audio_inbox folder and transcribes new files
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiofiles
import httpx
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from app.core.config import settings

logger = logging.getLogger(__name__)

AUDIO_INBOX = Path(settings.audio_inbox_path)
AUDIO_ARCHIVE = Path(settings.audio_archive_path)
AUDIO_EXTENSIONS = {'.m4a', '.wav', '.ogg', '.mp3', '.webm', '.mp4'}


class AudioInboxHandler(FileSystemEventHandler):
    """Watchdog handler for new audio files in inbox."""

    def __init__(self, callback):
        self.callback = callback
        self._loop = None

    def set_loop(self, loop):
        self._loop = loop

    def on_created(self, event):
        if not event.is_directory and Path(event.src_path).suffix.lower() in AUDIO_EXTENSIONS:
            if self._loop:
                asyncio.run_coroutine_threadsafe(
                    self.callback(Path(event.src_path)),
                    self._loop
                )


class WhisperService:
    """
    Transcription pipeline:
    1. File dropped into audio_inbox (from Galaxy Watch sync, Telegram, or manual)
    2. WhisperService picks it up, sends to Whisper API container
    3. Transcript appended to Obsidian Daily Note under #clinical-capture
    4. Telegram notification sent
    5. File archived
    """

    def __init__(self):
        self.api_url = settings.whisper_api_url
        self.client = httpx.AsyncClient(timeout=120.0)  # Audio can be slow
        self._observer: Optional[Observer] = None
        self._messaging = None
        self._obsidian = None

    def set_dependencies(self, messaging, obsidian):
        self._messaging = messaging
        self._obsidian = obsidian

    async def transcribe_file(self, audio_path: Path) -> Optional[str]:
        """Transcribe an audio file via Whisper API container."""
        try:
            logger.info(f"Transcribing: {audio_path.name}")
            async with aiofiles.open(audio_path, 'rb') as f:
                audio_bytes = await f.read()
            return await self.transcribe_bytes(audio_bytes, audio_path.name)
        except Exception as e:
            logger.error(f"Transcription error for {audio_path.name}: {e}")
            return None

    async def transcribe_bytes(self, audio_bytes: bytes, filename: str) -> Optional[str]:
        """Transcribe raw audio bytes via Whisper API."""
        try:
            files = {"file": (filename, audio_bytes, "audio/mpeg")}
            resp = await self.client.post(
                f"{self.api_url}/asr",
                files=files,
                params={"task": "transcribe", "language": "en", "output": "txt"},
                timeout=90.0
            )
            if resp.status_code == 200:
                transcript = resp.text.strip()
                if transcript:
                    logger.info(f"Transcribed: {transcript[:100]}")
                    return transcript
            else:
                logger.error(f"Whisper API error {resp.status_code}: {resp.text[:200]}")
                return None
        except httpx.ConnectError:
            logger.warning("Whisper API not reachable — is the container running?")
            return None
        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            return None

    async def process_new_audio(self, audio_path: Path):
        """Full pipeline: transcribe → append to vault → notify → archive."""
        # Wait briefly for file to be fully written
        await asyncio.sleep(0.5)

        transcript = await self.transcribe_file(audio_path)
        if not transcript:
            logger.warning(f"No transcript from {audio_path.name}")
            return

        timestamp = datetime.now().strftime("%H:%M")

        # Append to Obsidian Daily Note
        if self._obsidian:
            await self._obsidian.append_clinical_capture(transcript, timestamp)

        # Notify via Telegram
        if self._messaging:
            msg = f"📋 *Clinical Capture* — {timestamp}\n\n_{transcript}_\n\n_Added to Daily Note ✓_"
            await self._messaging.send(msg, channel="telegram")

        # Archive processed audio
        AUDIO_ARCHIVE.mkdir(parents=True, exist_ok=True)
        archive_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{audio_path.name}"
        audio_path.rename(AUDIO_ARCHIVE / archive_name)
        logger.info(f"Archived: {archive_name}")

    def start_watching(self, loop):
        """Start watching the audio inbox folder."""
        AUDIO_INBOX.mkdir(parents=True, exist_ok=True)
        handler = AudioInboxHandler(self.process_new_audio)
        handler.set_loop(loop)
        self._observer = Observer()
        self._observer.schedule(handler, str(AUDIO_INBOX), recursive=False)
        self._observer.start()
        logger.info(f"Watching audio inbox: {AUDIO_INBOX}")

    def stop_watching(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None


# Global instance
whisper_service = WhisperService()
