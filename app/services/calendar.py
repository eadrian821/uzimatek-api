"""
Calendar Service
Integration with Google Calendar API
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']

class CalendarService:
    """Service for managing Google Calendar events"""
    
    def __init__(self):
        self.creds = self._get_credentials()
        self.service = build('calendar', 'v3', credentials=self.creds) if self.creds else None

    def _get_credentials(self):
        """Helper to authenticate with Google Calendar API"""
        creds = None
        if settings.google_token_path and os.path.exists(settings.google_token_path):
            creds = Credentials.from_authorized_user_file(settings.google_token_path, SCOPES)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif settings.google_credentials_path and os.path.exists(settings.google_credentials_path):
                flow = InstalledAppFlow.from_client_secrets_file(settings.google_credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
                
            if creds and settings.google_token_path:
                with open(settings.google_token_path, 'w') as token:
                    token.write(creds.to_json())
        return creds

    async def get_upcoming_events(self, max_results: int = 10) -> List[Dict[str, Any]]:
        """Get upcoming calendar events"""
        if not self.service:
            logger.warning("Calendar service not initialized")
            return []
            
        try:
            now = datetime.utcnow().isoformat() + 'Z'
            events_result = self.service.events().list(
                calendarId='primary', timeMin=now,
                maxResults=max_results, singleEvents=True,
                orderBy='startTime'
            ).execute()
            return events_result.get('items', [])
        except HttpError as error:
            logger.error(f"Calendar error: {error}")
            return []

    async def create_event(self, summary: str, start_time: datetime, end_time: datetime, 
                           description: str = "", location: str = "") -> Optional[Dict[str, Any]]:
        """Create a new calendar event"""
        if not self.service:
            return None
            
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': settings.user_timezone,
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': settings.user_timezone,
            },
        }
        
        try:
            event = self.service.events().insert(calendarId='primary', body=event).execute()
            logger.info(f"Event created: {event.get('htmlLink')}")
            return event
        except HttpError as error:
            logger.error(f"Calendar error: {error}")
            return None

# Global calendar service instance
calendar = CalendarService()
