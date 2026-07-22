import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.orchestrator import Orchestrator, Intent, AgentResponse

@pytest.fixture
def orchestrator():
    with patch('app.core.orchestrator.AsyncAnthropic'):
        orch = Orchestrator()
        return orch

@pytest.mark.asyncio
async def test_orchestrator_classification(orchestrator):
    orchestrator.client.messages.create = AsyncMock()
    orchestrator.client.messages.create.return_value.content = [
        MagicMock(text='{"primary_intent": "pa_calendar", "confidence": 0.9, "secondary_domains": [], "reasoning": "testing"}')
    ]
    
    intent, confidence, secondary = await orchestrator.classify_intent("Schedule a meeting")
    assert intent == Intent.PA_CALENDAR
    assert confidence == 0.9

@pytest.mark.asyncio
async def test_orchestrator_routing(orchestrator):
    # Mock classification
    orchestrator.classify_intent = AsyncMock(return_value=(Intent.PA_CALENDAR, 0.9, []))
    
    # Mock agent
    mock_agent = MagicMock()
    mock_agent.process = AsyncMock(return_value=AgentResponse(agent="pa", content="Calendar action taken"))
    orchestrator.register_agent("pa", mock_agent)
    
    response = await orchestrator.process_message("Schedule meeting")
    assert response.agent == "pa"
    assert response.content == "Calendar action taken"
