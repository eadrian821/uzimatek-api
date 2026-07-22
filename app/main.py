"""
JARVIS - Main FastAPI Application
AI Personal Assistant + Medical Cognitive Brain for Adrian Wekesa
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.orchestrator import orchestrator
from app.agents import MedicalAgent, TradingAgent, BusinessAgent, PAAgent
from app.agents.delta_agent import DeltaAgent
from app.agents.atomization_agent import AtomizationAgent
from app.agents.socratic_agent import SocraticAgent, CrucibleAgent
from app.services.brain_service import BrainService
from app.services.messaging import messaging
from app.services.scheduler import scheduler
from app.services.memory import memory
from app.services.obsidian_service import obsidian
from app.services.whisper_service import whisper_service
from app.api import router as api_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

async def telegram_long_polling():
    """Long-polling loop for local development without webhooks."""
    import httpx
    offset = 0
    # Delete any existing webhook to ensure getUpdates works
    async with httpx.AsyncClient() as client:
        try:
            await client.get(f"https://api.telegram.org/bot{settings.telegram_bot_token}/deleteWebhook")
        except Exception as e:
            logger.warning(f"Failed to delete webhook (safe to ignore): {e}")
        
    async with httpx.AsyncClient(timeout=60.0) as client:
        while True:
            try:
                url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/getUpdates"
                resp = await client.get(url, params={"offset": offset, "timeout": 30})
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        
                        # Process message
                        response = await messaging.handle_incoming("telegram", update)
                        if response:
                            chat = update.get("message", {}).get("chat", {})
                            chat_id = chat.get("id")
                            if chat_id:
                                from app.services.messaging import OutgoingMessage
                                await messaging.telegram.send_message(
                                    OutgoingMessage(
                                        channel="telegram",
                                        recipient_id=str(chat_id),
                                        content=response
                                    )
                                )
            except Exception as e:
                logger.error(f"Telegram polling error: {e}")
                await asyncio.sleep(5)
            await asyncio.sleep(0.5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting JARVIS Medical Brain...")
    
    # Start Telegram Long Polling
    if settings.telegram_bot_token:
        asyncio.create_task(telegram_long_polling())
        logger.info("Started Telegram long-polling loop")

    # 1. Initialize memory services (Qdrant collections created here)
    await memory.connect()
    logger.info("Memory services connected — all Qdrant collections initialized")
    
    # 2. Register standard agents
    if settings.enable_medical_agent:
        orchestrator.register_agent("medical", MedicalAgent())
    if settings.enable_trading_agent:
        orchestrator.register_agent("trading", TradingAgent())
    if settings.enable_business_agent:
        orchestrator.register_agent("business", BusinessAgent())
    orchestrator.register_agent("pa", PAAgent())
    
    # 3. Register medical brain agents
    if settings.enable_medical_brain:
        brain_service = BrainService()
        orchestrator.register_agent("delta", DeltaAgent())
        orchestrator.register_agent("atomization", AtomizationAgent())
        orchestrator.register_agent("socratic", SocraticAgent())
        orchestrator.register_agent("crucible", CrucibleAgent())
        orchestrator.register_agent("brain", brain_service)
        logger.info("Medical brain agents registered: delta, atomization, socratic, crucible, brain")
    
    logger.info(f"All agents registered: {list(orchestrator.agents.keys())}")
    
    # 4. Set up messaging handler
    async def handle_message(msg):
        response = await orchestrator.process_message(
            message=msg.content,
            channel=msg.channel,
            session_id=msg.sender_id,
            attachments=msg.attachments
        )
        return response.content
    
    messaging.set_message_handler(handle_message)
    
    # 5. Wire Whisper → Obsidian dependencies
    whisper_service.set_dependencies(messaging, obsidian)
    
    # 6. Start file system watchers
    loop = asyncio.get_event_loop()
    if settings.enable_medical_brain:
        from app.services.corpus_ingestion import corpus
        # Obsidian vault watcher: re-index on vault changes
        async def on_vault_change(path, event_type):
            logger.info(f"Vault change: {path.name} ({event_type})")
            count = await corpus.ingest_single_file(path)
            if count:
                logger.info(f"Re-indexed {count} chunks from {path.name}")
        obsidian.set_ingestion_callback(on_vault_change)
        obsidian.start_watching(loop)
        # Audio inbox watcher: transcribe → append to daily note
        whisper_service.start_watching(loop)
        logger.info("Watchers started: Obsidian vault + audio inbox")
    
    # 7. Set up scheduler
    scheduler.set_orchestrator(orchestrator)
    scheduler.set_messaging(messaging)
    await scheduler.start()
    
    # 8. Schedule medical brain cron jobs
    if settings.enable_medical_brain:
        from apscheduler.triggers.cron import CronTrigger
        # Morning brief at 06:30 EAT
        scheduler.scheduler.add_job(
            _send_morning_brief,
            CronTrigger(hour=6, minute=30, timezone=settings.user_timezone),
            id="morning_brief",
            replace_existing=True
        )
        # Brain proactive connections at 19:00 EAT
        scheduler.scheduler.add_job(
            _send_evening_connections,
            CronTrigger(hour=19, minute=0, timezone=settings.user_timezone),
            id="evening_connections",
            replace_existing=True
        )
        logger.info("Medical brain cron jobs scheduled")
    
    # 9. Set Telegram bot commands (includes all new medical commands)
    if settings.telegram_bot_token:
        await messaging.telegram.set_commands()
    
    logger.info("JARVIS Medical Brain is ready! 🧠")
    
    yield
    
    # Shutdown
    logger.info("Shutting down JARVIS...")
    if settings.enable_medical_brain:
        obsidian.stop_watching()
        whisper_service.stop_watching()
    await scheduler.stop()
    await memory.disconnect()
    logger.info("JARVIS shutdown complete")


async def _send_morning_brief():
    """Scheduled task: morning brief via Telegram."""
    try:
        brain = orchestrator.agents.get("brain")
        if brain:
            response = await brain.generate_morning_brief()
            await messaging.send(response.content, channel="telegram")
    except Exception as e:
        logger.error(f"Morning brief error: {e}")


async def _send_evening_connections():
    """Scheduled task: proactive knowledge connections via Telegram."""
    try:
        brain = orchestrator.agents.get("brain")
        if brain:
            connections = await brain._find_connections()
            if connections:
                msg = "🧠 *Evening Brain Connections*\n\n" + "\n\n".join(connections[:3])
                await messaging.send(msg, channel="telegram")
    except Exception as e:
        logger.error(f"Evening connections error: {e}")



# Create FastAPI app
app = FastAPI(
    title="JARVIS",
    description="Intelligent Personal Assistant for Adrian Wekesa",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api")


# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "JARVIS",
        "timestamp": datetime.now().isoformat(),
        "agents": list(orchestrator.agents.keys()),
        "version": "1.0.0"
    }


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "JARVIS - AI Personal Assistant",
        "status": "online",
        "docs": "/docs",
        "health": "/health"
    }


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if settings.debug else "An error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        workers=1 if settings.debug else settings.workers
    )
