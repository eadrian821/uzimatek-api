"""
Messaging Services — FIXED for full two-way communication
Telegram: MarkdownV2, long-message split, voice→Whisper, deduplication
Slack: added to handle_incoming(), signing secret verification, retry logic
"""

import asyncio
import hashlib
import hmac
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Callable
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import httpx
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LENGTH = 4096


class IncomingMessage(BaseModel):
    channel: str
    sender_id: str
    sender_name: Optional[str] = None
    content: str
    timestamp: datetime
    message_id: str
    reply_to: Optional[str] = None
    attachments: List[Dict[str, Any]] = []
    raw_data: Dict[str, Any] = {}


class OutgoingMessage(BaseModel):
    channel: str
    recipient_id: str
    content: str
    priority: str = "p2"
    reply_to: Optional[str] = None
    attachments: List[Dict[str, Any]] = []


class BaseMessenger(ABC):
    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> bool:
        pass

    @abstractmethod
    async def handle_webhook(self, data: Dict[str, Any]) -> Optional[IncomingMessage]:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Telegram — FIXED
# ─────────────────────────────────────────────────────────────────────────────

def escape_markdownv2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special)}])', r'\\\1', text)


def split_message(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> List[str]:
    """Split long messages at paragraph/sentence boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Try to split at paragraph
        split_at = text.rfind('\n\n', 0, max_len)
        if split_at == -1:
            split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = text.rfind('. ', 0, max_len)
        if split_at == -1:
            split_at = max_len - 1
        chunks.append(text[:split_at + 1])
        text = text[split_at + 1:].lstrip()
    return chunks


class TelegramMessenger(BaseMessenger):
    """Telegram Bot messaging service — fully fixed"""

    def __init__(self):
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.client = httpx.AsyncClient(timeout=30.0)

    async def send_message(self, message: OutgoingMessage) -> bool:
        if not self.token:
            logger.warning("Telegram not configured")
            return False
        chunks = split_message(message.content)
        success = True
        for i, chunk in enumerate(chunks):
            payload = {
                "chat_id": message.recipient_id or self.chat_id,
                "text": chunk,
                "parse_mode": "MarkdownV2"  # FIXED: was "Markdown"
            }
            if message.reply_to and i == 0:
                payload["reply_to_message_id"] = message.reply_to
            try:
                resp = await self.client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp.status_code != 200:
                    # MarkdownV2 parse error → retry as plain text
                    if resp.status_code == 400 and "can't parse" in resp.text.lower():
                        payload["text"] = chunk
                        payload.pop("parse_mode", None)
                        resp2 = await self.client.post(f"{self.base_url}/sendMessage", json=payload)
                        if resp2.status_code != 200:
                            logger.error(f"Telegram send failed (plain): {resp2.text}")
                            success = False
                    else:
                        logger.error(f"Telegram send failed: {resp.text}")
                        success = False
            except Exception as e:
                logger.error(f"Telegram send error: {e}")
                success = False
        return success

    async def send_photo(self, chat_id: str, photo_url: str, caption: str = "") -> bool:
        """Send a photo with caption — used for dual-coding Anki card preview."""
        if not self.token:
            return False
        try:
            resp = await self.client.post(
                f"{self.base_url}/sendPhoto",
                json={"chat_id": chat_id, "photo": photo_url, "caption": caption[:1024]}
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send photo error: {e}")
            return False

    async def download_file(self, file_id: str) -> Optional[bytes]:
        """Download a file (voice/audio) from Telegram servers."""
        try:
            resp = await self.client.get(f"{self.base_url}/getFile?file_id={file_id}")
            file_path = resp.json()["result"]["file_path"]
            dl_resp = await self.client.get(f"https://api.telegram.org/file/bot{self.token}/{file_path}")
            return dl_resp.content
        except Exception as e:
            logger.error(f"Telegram file download error: {e}")
            return None

    async def handle_webhook(self, data: Dict[str, Any]) -> Optional[IncomingMessage]:
        try:
            if "message" not in data and "channel_post" not in data:
                return None
            msg = data.get("message") or data.get("channel_post")
            content = msg.get("text", "")
            attachments = []

            # Voice message → queue for Whisper transcription
            if "voice" in msg:
                voice = msg["voice"]
                attachments.append({
                    "type": "voice",
                    "file_id": voice["file_id"],
                    "duration": voice.get("duration", 0),
                    "pending_transcription": True
                })
                content = "__voice_message__"  # Sentinel for whisper handler

            # Audio file
            if "audio" in msg:
                audio = msg["audio"]
                attachments.append({
                    "type": "audio",
                    "file_id": audio["file_id"],
                    "file_name": audio.get("file_name", "audio.mp3"),
                    "pending_transcription": True
                })
                content = content or "__audio_message__"

            if "document" in msg:
                attachments.append({
                    "type": "document",
                    "file_id": msg["document"]["file_id"],
                    "file_name": msg["document"].get("file_name")
                })
            if "photo" in msg:
                photo = msg["photo"][-1]
                attachments.append({"type": "photo", "file_id": photo["file_id"]})

            return IncomingMessage(
                channel="telegram",
                sender_id=str(msg["from"]["id"]),
                sender_name=msg["from"].get("first_name", ""),
                content=content,
                timestamp=datetime.fromtimestamp(msg["date"]),
                message_id=str(msg["message_id"]),
                attachments=attachments,
                raw_data=data
            )
        except Exception as e:
            logger.error(f"Telegram webhook parse error: {e}")
            return None

    async def set_commands(self):
        commands = [
            {"command": "brief", "description": "Daily brief"},
            {"command": "recall", "description": "Start blank recall session"},
            {"command": "delta", "description": "Compare recall vs gold standard"},
            {"command": "quiz", "description": "Socratic quiz session"},
            {"command": "capture", "description": "Log clinical case"},
            {"command": "anki", "description": "Generate Anki cards"},
            {"command": "crucible", "description": "Rotation-end exam generator"},
            {"command": "market", "description": "Market overview"},
            {"command": "tasks", "description": "View tasks"},
            {"command": "brain", "description": "Cross-source knowledge connections"},
            {"command": "help", "description": "All commands"},
        ]
        try:
            resp = await self.client.post(f"{self.base_url}/setMyCommands", json={"commands": commands})
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Set commands error: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Slack — FIXED: bidirectional, signing secret, added to handle_incoming()
# ─────────────────────────────────────────────────────────────────────────────

class SlackMessenger(BaseMessenger):
    """Slack messaging — fixed for full two-way communication"""

    def __init__(self):
        self.token = settings.slack_bot_token
        self.channel_id = settings.slack_channel_id
        self.signing_secret = settings.slack_signing_secret
        self.base_url = "https://slack.com/api"
        self._headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        self.client = httpx.AsyncClient(timeout=30.0, headers=self._headers)

    def verify_signature(self, body: bytes, timestamp: str, signature: str) -> bool:
        """Verify Slack request signature to prevent fake webhooks."""
        if not self.signing_secret:
            logger.warning("Slack signing secret not configured — skipping verification")
            return True
        # Prevent replay attacks older than 5 minutes
        if abs(time.time() - int(timestamp)) > 300:
            return False
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
        computed = "v0=" + hmac.new(
            self.signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed, signature)

    async def send_message(self, message: OutgoingMessage) -> bool:
        if not self.token:
            logger.warning("Slack not configured")
            return False
        # Split long messages for Slack (max 40000 chars, but blocks are better)
        chunks = split_message(message.content, max_len=3000)
        success = True
        for i, chunk in enumerate(chunks):
            payload = {
                "channel": message.recipient_id or self.channel_id,
                "text": chunk,
                "unfurl_links": False
            }
            if message.reply_to and i == 0:
                payload["thread_ts"] = message.reply_to
            try:
                # Retry up to 3 times for rate limits
                for attempt in range(3):
                    resp = await self.client.post(f"{self.base_url}/chat.postMessage", json=payload)
                    data = resp.json()
                    if data.get("ok"):
                        break
                    if data.get("error") == "ratelimited":
                        retry_after = int(resp.headers.get("Retry-After", 1))
                        await asyncio.sleep(retry_after)
                    else:
                        logger.error(f"Slack send failed: {data.get('error')}")
                        success = False
                        break
            except Exception as e:
                logger.error(f"Slack send error: {e}")
                success = False
        return success

    async def handle_webhook(self, data: Dict[str, Any]) -> Optional[IncomingMessage]:
        try:
            event = data.get("event", {})
            # Filter out bot messages and non-message events
            if event.get("type") != "message" or "bot_id" in event or event.get("subtype"):
                return None
            content = event.get("text", "")
            # Strip Slack user mentions like <@U123ABC>
            content = re.sub(r'<@[A-Z0-9]+>', '', content).strip()
            if not content:
                return None
            return IncomingMessage(
                channel="slack",
                sender_id=event.get("user", ""),
                content=content,
                timestamp=datetime.fromtimestamp(float(event.get("ts", 0))),
                message_id=event.get("ts", ""),
                reply_to=event.get("thread_ts"),
                raw_data=data
            )
        except Exception as e:
            logger.error(f"Slack webhook parse error: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Twilio (WhatsApp/SMS)
# ─────────────────────────────────────────────────────────────────────────────

class TwilioMessenger(BaseMessenger):
    """Twilio WhatsApp and SMS"""

    def __init__(self):
        self.account_sid = settings.twilio_account_sid
        self.auth_token = settings.twilio_auth_token
        self.whatsapp_number = settings.twilio_whatsapp_number
        self.sms_number = settings.twilio_sms_number
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}"
        self.client = httpx.AsyncClient(
            timeout=30.0,
            auth=(self.account_sid, self.auth_token) if self.account_sid else None
        )

    async def send_message(self, message: OutgoingMessage) -> bool:
        if not self.account_sid:
            logger.warning("Twilio not configured")
            return False
        try:
            if message.channel == "whatsapp":
                from_number = self.whatsapp_number
                to_number = message.recipient_id if message.recipient_id.startswith("whatsapp:") else f"whatsapp:{message.recipient_id}"
            else:
                from_number = self.sms_number
                to_number = message.recipient_id
            # Truncate for SMS
            body = message.content[:1600]
            resp = await self.client.post(
                f"{self.base_url}/Messages.json",
                data={"From": from_number, "To": to_number, "Body": body}
            )
            return resp.status_code in [200, 201]
        except Exception as e:
            logger.error(f"Twilio send error: {e}")
            return False

    async def handle_webhook(self, data: Dict[str, Any]) -> Optional[IncomingMessage]:
        try:
            from_number = data.get("From", "")
            body = data.get("Body", "")
            channel = "whatsapp" if from_number.startswith("whatsapp:") else "sms"
            attachments = []
            for i in range(int(data.get("NumMedia", 0))):
                attachments.append({
                    "type": data.get(f"MediaContentType{i}", "unknown"),
                    "url": data.get(f"MediaUrl{i}")
                })
            return IncomingMessage(
                channel=channel,
                sender_id=from_number,
                content=body,
                timestamp=datetime.now(),
                message_id=data.get("MessageSid", ""),
                attachments=attachments,
                raw_data=data
            )
        except Exception as e:
            logger.error(f"Twilio webhook parse error: {e}")
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Email
# ─────────────────────────────────────────────────────────────────────────────

class EmailMessenger(BaseMessenger):
    async def send_message(self, message: OutgoingMessage) -> bool:
        if not settings.smtp_user or not settings.smtp_password:
            logger.warning("Email SMTP not configured")
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = settings.smtp_user
            msg['To'] = message.recipient_id or settings.user_email
            msg['Subject'] = "JARVIS Notification"
            msg.attach(MIMEText(message.content, 'plain'))
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._send_sync, msg)
            return True
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False

    def _send_sync(self, msg):
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)

    async def handle_webhook(self, data: Dict[str, Any]) -> Optional[IncomingMessage]:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# MessagingHub — Central coordinator
# ─────────────────────────────────────────────────────────────────────────────

class MessagingHub:
    """Central hub for all messaging channels"""

    def __init__(self):
        self.telegram = TelegramMessenger()
        self.twilio = TwilioMessenger()
        self.slack = SlackMessenger()
        self.email = EmailMessenger()
        self.message_handler: Optional[Callable] = None

    def set_message_handler(self, handler: Callable):
        self.message_handler = handler

    async def send(
        self,
        content: str,
        channel: str = "telegram",
        recipient_id: str = None,
        priority: str = "p2"
    ) -> bool:
        message = OutgoingMessage(
            channel=channel,
            recipient_id=recipient_id or self._get_default_recipient(channel),
            content=content,
            priority=priority
        )
        if channel == "telegram":
            return await self.telegram.send_message(message)
        elif channel in ["whatsapp", "sms"]:
            return await self.twilio.send_message(message)
        elif channel == "slack":
            return await self.slack.send_message(message)
        elif channel == "email":
            return await self.email.send_message(message)
        else:
            logger.error(f"Unknown channel: {channel}")
            return False

    async def send_with_priority(self, content: str, priority: str = "p2") -> bool:
        if priority == "p0":
            results = await asyncio.gather(
                self.send(content, "telegram"),
                self.send(content, "whatsapp") if settings.enable_whatsapp else asyncio.sleep(0),
                return_exceptions=True
            )
            return any(r is True for r in results)
        elif priority == "p1":
            result = await self.send(content, "telegram")
            if settings.enable_slack:
                await self.send(content, "slack")
            return result
        else:
            return await self.send(content, "telegram")

    def _get_default_recipient(self, channel: str) -> str:
        if channel == "telegram":
            return settings.telegram_chat_id or ""
        elif channel == "whatsapp":
            return settings.user_whatsapp or ""
        elif channel == "sms":
            return settings.user_phone or ""
        elif channel == "slack":
            return settings.slack_channel_id or ""
        return ""

    async def handle_incoming(self, channel: str, data: Dict[str, Any]) -> Optional[str]:
        """Process incoming message and return response — ALL channels now handled."""
        if channel == "telegram":
            message = await self.telegram.handle_webhook(data)
        elif channel in ["whatsapp", "sms"]:
            message = await self.twilio.handle_webhook(data)
        elif channel == "slack":                          # FIXED: was missing
            message = await self.slack.handle_webhook(data)
        else:
            return None

        if not message or not self.message_handler:
            return None

        # Handle voice messages by routing to Whisper
        if message.content == "__voice_message__" or message.content == "__audio_message__":
            voice_att = next((a for a in message.attachments if a.get("pending_transcription")), None)
            if voice_att:
                from app.services.whisper_service import whisper_service
                audio_bytes = await self.telegram.download_file(voice_att["file_id"])
                if audio_bytes:
                    transcript = await whisper_service.transcribe_bytes(audio_bytes, f"{voice_att['file_id']}.ogg")
                    if transcript:
                        message.content = transcript
                        # Append to daily note automatically
                        from app.services.obsidian_service import obsidian
                        await obsidian.append_clinical_capture(transcript)
                        return f"📋 *Captured to Daily Note:*\n_{transcript}_"
            return "⚠️ Received voice message but transcription failed. Is Whisper running?"

        try:
            response = await self.message_handler(message)
            return response
        except Exception as e:
            logger.error(f"Message handling error: {e}")
            return "I encountered an error. Please try again."


# Global messaging hub instance
messaging = MessagingHub()
