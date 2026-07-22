import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from app.services.calendar import CalendarService

@pytest.fixture
def mock_calendar_service():
    with patch('app.services.calendar.build') as mock_build, \
         patch('app.services.calendar.CalendarService._get_credentials') as mock_creds:
        mock_creds.return_value = MagicMock()
        service = CalendarService()
        # Explicitly set service since build was called in __init__
        service.service = mock_build.return_value
        yield service, mock_build

@pytest.mark.asyncio
async def test_calendar_get_events(mock_calendar_service):
    service, mock_build = mock_calendar_service
    mock_list = mock_build.return_value.events.return_value.list
    mock_list.return_value.execute.return_value = {'items': [{'summary': 'Test Event'}]}
    
    events = await service.get_upcoming_events()
    assert len(events) == 1
    assert events[0]['summary'] == 'Test Event'

@pytest.mark.asyncio
async def test_calendar_create_event(mock_calendar_service):
    service, mock_build = mock_calendar_service
    mock_insert = mock_build.return_value.events.return_value.insert
    mock_insert.return_value.execute.return_value = {'summary': 'Meeting'}
    
    start = datetime.now()
    end = start + timedelta(hours=1)
    event = await service.create_event("Meeting", start, end)
    
    assert event is not None
    assert event['summary'] == 'Meeting'
    mock_insert.assert_called_once()
