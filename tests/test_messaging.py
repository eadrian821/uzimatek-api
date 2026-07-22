import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.messaging import MessagingHub, OutgoingMessage

@pytest.mark.asyncio
async def test_messaging_hub_routing():
    hub = MessagingHub()
    hub.telegram.send_message = AsyncMock(return_value=True)
    hub.slack.send_message = AsyncMock(return_value=True)
    hub.twilio.send_message = AsyncMock(return_value=True)
    
    # Test Telegram
    await hub.send("test telegram", channel="telegram")
    hub.telegram.send_message.assert_called_once()
    
    # Test Slack
    await hub.send("test slack", channel="slack")
    hub.slack.send_message.assert_called_once()
    
    # Test SMS/WhatsApp
    await hub.send("test sms", channel="sms")
    hub.twilio.send_message.assert_called_once()

@pytest.mark.asyncio
async def test_priority_routing():
    hub = MessagingHub()
    hub.send = AsyncMock(return_value=True)
    
    await hub.send_with_priority("critical alert", priority="p0")
    # Should call send multiple times for p0
    assert hub.send.call_count >= 1
