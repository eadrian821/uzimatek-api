"""
Scheduler Service
Handles scheduled tasks, daily rhythms, and proactive notifications
"""

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Dict, List, Callable, Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)


class DailyRhythm:
    """Represents a scheduled daily action"""
    def __init__(
        self,
        name: str,
        time_str: str,  # HH:MM format
        action: str,
        channels: List[str] = None,
        days: List[int] = None,  # 0=Monday
        enabled: bool = True
    ):
        self.name = name
        self.time_str = time_str
        self.action = action
        self.channels = channels or ["telegram", "slack"]
        self.days = days or [0, 1, 2, 3, 4, 5, 6]  # All days
        self.enabled = enabled
        
        # Parse time
        parts = time_str.split(":")
        self.hour = int(parts[0])
        self.minute = int(parts[1]) if len(parts) > 1 else 0


# Default daily rhythms based on JARVIS spec
DEFAULT_RHYTHMS = [
    DailyRhythm("wake_analysis", "05:30", "wake_brief", ["telegram"]),
    DailyRhythm("morning_brief", "06:00", "morning_brief", ["telegram", "whatsapp"]),
    DailyRhythm("pre_rotation", "06:30", "rotation_prep", ["telegram"], days=[0,1,2,3,4]),  # Weekdays
    DailyRhythm("trading_open", "08:00", "trading_brief", ["telegram"]),
    DailyRhythm("mid_morning", "10:00", "mid_morning_check", ["telegram"]),
    DailyRhythm("midday_pulse", "12:30", "midday_brief", ["telegram"]),
    DailyRhythm("afternoon_brief", "15:00", "afternoon_brief", ["telegram"]),
    DailyRhythm("market_close", "17:00", "trading_review", ["telegram"]),
    DailyRhythm("evening_transition", "19:00", "evening_brief", ["telegram"]),
    DailyRhythm("study_support", "21:00", "study_brief", ["telegram"]),
    DailyRhythm("night_wrap", "22:30", "night_brief", ["telegram"]),
]


class SchedulerService:
    """
    Manages all scheduled tasks and daily rhythms for JARVIS
    """
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.user_timezone))
        self.rhythms: Dict[str, DailyRhythm] = {}
        self.handlers: Dict[str, Callable] = {}
        self._orchestrator = None
        self._messaging = None
        
    def set_orchestrator(self, orchestrator):
        """Set the orchestrator for generating briefs"""
        self._orchestrator = orchestrator
        
    def set_messaging(self, messaging):
        """Set the messaging hub for sending notifications"""
        self._messaging = messaging
    
    async def start(self):
        """Start the scheduler"""
        # Load default rhythms
        for rhythm in DEFAULT_RHYTHMS:
            self.add_rhythm(rhythm)
        
        # Add interval tasks
        self._add_interval_tasks()
        
        # Start scheduler
        self.scheduler.start()
        logger.info("Scheduler started")
    
    async def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")
    
    def add_rhythm(self, rhythm: DailyRhythm):
        """Add a daily rhythm to the scheduler"""
        if not rhythm.enabled:
            return
        
        self.rhythms[rhythm.name] = rhythm
        
        # Create cron trigger
        trigger = CronTrigger(
            hour=rhythm.hour,
            minute=rhythm.minute,
            day_of_week=",".join(str(d) for d in rhythm.days),
            timezone=ZoneInfo(settings.user_timezone)
        )
        
        # Add job
        self.scheduler.add_job(
            self._execute_rhythm,
            trigger,
            args=[rhythm],
            id=f"rhythm_{rhythm.name}",
            replace_existing=True
        )
        
        logger.info(f"Added rhythm: {rhythm.name} at {rhythm.time_str}")
    
    def remove_rhythm(self, name: str):
        """Remove a daily rhythm"""
        if name in self.rhythms:
            del self.rhythms[name]
            try:
                self.scheduler.remove_job(f"rhythm_{name}")
            except:
                pass
    
    def _add_interval_tasks(self):
        """Add interval-based tasks"""
        
        # Email check every 15 minutes
        self.scheduler.add_job(
            self._check_emails,
            IntervalTrigger(minutes=15),
            id="email_check",
            replace_existing=True
        )
        
        # Market data refresh every 5 minutes during trading hours
        self.scheduler.add_job(
            self._refresh_market_data,
            IntervalTrigger(minutes=5),
            id="market_refresh",
            replace_existing=True
        )
        
        # Health reminder every 90 minutes
        self.scheduler.add_job(
            self._health_reminder,
            IntervalTrigger(minutes=90),
            id="health_reminder",
            replace_existing=True
        )
    
    async def _execute_rhythm(self, rhythm: DailyRhythm):
        """Execute a scheduled rhythm"""
        logger.info(f"Executing rhythm: {rhythm.name}")
        
        try:
            # Generate content based on action type
            content = await self._generate_rhythm_content(rhythm.action)
            
            if content and self._messaging:
                # Send to configured channels
                for channel in rhythm.channels:
                    await self._messaging.send(
                        content=content,
                        channel=channel,
                        priority="p2"
                    )
                    
        except Exception as e:
            logger.error(f"Rhythm execution error ({rhythm.name}): {e}")
    
    async def _generate_rhythm_content(self, action: str) -> Optional[str]:
        """Generate content for a rhythm action"""
        
        if not self._orchestrator:
            return None
        
        action_map = {
            "wake_brief": "morning",
            "morning_brief": "morning",
            "rotation_prep": "morning",
            "trading_brief": "morning",
            "mid_morning_check": "midday",
            "midday_brief": "midday",
            "afternoon_brief": "midday",
            "trading_review": "evening",
            "evening_brief": "evening",
            "study_brief": "evening",
            "night_brief": "evening"
        }
        
        brief_type = action_map.get(action, "morning")
        
        try:
            response = await self._orchestrator.generate_brief(brief_type)
            return response.content
        except Exception as e:
            logger.error(f"Brief generation error: {e}")
            return None
    
    async def _check_emails(self):
        """Check for new emails (placeholder)"""
        # This would integrate with Gmail API
        pass
    
    async def _refresh_market_data(self):
        """Refresh market data (placeholder)"""
        # This would fetch fresh market data
        # Only execute during trading hours
        tz = ZoneInfo(settings.user_timezone)
        now = datetime.now(tz)
        if 8 <= now.hour < 17 and now.weekday() < 5:
            pass  # Fetch market data
    
    async def _health_reminder(self):
        """Send health reminders"""
        tz = ZoneInfo(settings.user_timezone)
        now = datetime.now(tz)
        
        # Only during waking hours
        if 7 <= now.hour < 22:
            if self._messaging:
                await self._messaging.send(
                    content="💧 **Hydration Reminder**\nTime for a quick water break!",
                    channel="telegram",
                    priority="p3"
                )
    
    def register_handler(self, action: str, handler: Callable):
        """Register a custom handler for an action"""
        self.handlers[action] = handler
    
    def get_upcoming(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get upcoming scheduled events"""
        upcoming = []
        tz = ZoneInfo(settings.user_timezone)
        now = datetime.now(tz)
        cutoff = now + timedelta(hours=hours)
        
        for job in self.scheduler.get_jobs():
            next_run = job.next_run_time
            if next_run and next_run < cutoff:
                upcoming.append({
                    "id": job.id,
                    "next_run": next_run.isoformat(),
                    "name": job.id.replace("rhythm_", "")
                })
        
        return sorted(upcoming, key=lambda x: x["next_run"])


# Global scheduler instance
scheduler = SchedulerService()
