"""
JARVIS API Routes
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.orchestrator import orchestrator, AgentResponse
from app.services.messaging import messaging
from app.services.scheduler import scheduler
from app.services.memory import memory
from app.sha_claims.router import router as sha_router
from app.ehr.router import router as ehr_router

router = APIRouter()
router.include_router(sha_router)
router.include_router(ehr_router)


# ============================================
# Request/Response Models
# ============================================

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    channel: str = "api"
    attachments: Optional[List[Dict[str, Any]]] = None


class ChatResponse(BaseModel):
    response: str
    agent: str
    session_id: str
    confidence: float
    actions: List[Dict[str, Any]] = []
    follow_up: Optional[str] = None
    timestamp: str


class BriefRequest(BaseModel):
    brief_type: str = "morning"  # morning, midday, evening


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = None
    domain: str = "pa"
    priority: str = "p2"
    due_date: Optional[str] = None


class TaskResponse(BaseModel):
    id: str
    title: str
    domain: str
    priority: str
    status: str
    created_at: str


# ============================================
# Chat Endpoints
# ============================================

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint - process natural language messages
    """
    session_id = request.session_id or str(uuid4())
    
    # Store message in memory
    await memory.add_to_conversation(session_id, "user", request.message)
    
    # Process through orchestrator
    response = await orchestrator.process_message(
        message=request.message,
        channel=request.channel,
        session_id=session_id,
        attachments=request.attachments
    )
    
    # Store response in memory
    await memory.add_to_conversation(session_id, "assistant", response.content)
    
    return ChatResponse(
        response=response.content,
        agent=response.agent,
        session_id=session_id,
        confidence=response.confidence,
        actions=response.actions_taken,
        follow_up=response.follow_up_question,
        timestamp=datetime.now().isoformat()
    )


@router.get("/chat/history/{session_id}")
async def get_chat_history(session_id: str, limit: int = 50):
    """Get chat history for a session"""
    history = await memory.get_conversation(session_id, limit)
    return {"session_id": session_id, "messages": history}


# ============================================
# Brief Endpoints
# ============================================

@router.post("/brief")
async def generate_brief(request: BriefRequest):
    """Generate a scheduled brief"""
    response = await orchestrator.generate_brief(request.brief_type)
    return {
        "brief_type": request.brief_type,
        "content": response.content,
        "timestamp": datetime.now().isoformat()
    }


@router.get("/brief/morning")
async def morning_brief():
    """Get morning brief"""
    response = await orchestrator.generate_brief("morning")
    return {"content": response.content}


@router.get("/brief/evening")
async def evening_brief():
    """Get evening brief"""
    response = await orchestrator.generate_brief("evening")
    return {"content": response.content}


# ============================================
# Agent-Specific Endpoints
# ============================================

@router.get("/agents")
async def list_agents():
    """List all registered agents"""
    return {
        "agents": [
            {
                "name": name,
                "description": agent.description,
                "capabilities": agent.capabilities
            }
            for name, agent in orchestrator.agents.items()
        ]
    }


@router.post("/agents/{agent_name}/query")
async def query_agent(agent_name: str, request: ChatRequest):
    """Query a specific agent directly"""
    if agent_name not in orchestrator.agents:
        raise HTTPException(status_code=404, detail=f"Agent {agent_name} not found")
    
    agent = orchestrator.agents[agent_name]
    from app.core.orchestrator import Intent
    
    response = await agent.process(
        message=request.message,
        intent=Intent.GENERAL,
        context=orchestrator.context,
        attachments=request.attachments
    )
    
    return {
        "agent": agent_name,
        "response": response.content,
        "confidence": response.confidence
    }


# ============================================
# Task Endpoints
# ============================================

@router.post("/tasks", response_model=TaskResponse)
async def create_task(task: TaskCreate):
    """Create a new task"""
    task_id = str(uuid4())
    
    # Store task (would go to database)
    return TaskResponse(
        id=task_id,
        title=task.title,
        domain=task.domain,
        priority=task.priority,
        status="pending",
        created_at=datetime.now().isoformat()
    )


@router.get("/tasks")
async def list_tasks(domain: Optional[str] = None, status: Optional[str] = None):
    """List tasks with optional filters"""
    # Would query database
    return {"tasks": [], "filters": {"domain": domain, "status": status}}


# ============================================
# Trading Endpoints
# ============================================

@router.get("/trading/brief")
async def trading_brief():
    """Get current market brief"""
    if "trading" not in orchestrator.agents:
        raise HTTPException(status_code=404, detail="Trading agent not enabled")
    
    agent = orchestrator.agents["trading"]
    brief = await agent.generate_brief("morning")
    return {"brief": brief}


@router.post("/trading/log")
async def log_trade(
    symbol: str,
    direction: str,
    entry_price: float,
    quantity: float,
    strategy: Optional[str] = None,
    notes: Optional[str] = None
):
    """Log a trade"""
    trade_id = str(uuid4())
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry_price": entry_price,
        "quantity": quantity,
        "logged_at": datetime.now().isoformat()
    }


# ============================================
# Medical Endpoints
# ============================================

@router.post("/medical/flashcards")
async def generate_flashcards(content: str, topic: Optional[str] = None):
    """Generate flashcards from content"""
    if "medical" not in orchestrator.agents:
        raise HTTPException(status_code=404, detail="Medical agent not enabled")
    
    from app.core.orchestrator import Intent
    agent = orchestrator.agents["medical"]
    
    response = await agent.process(
        message=f"Create flashcards about {topic or 'this topic'}: {content}",
        intent=Intent.MEDICAL_FLASHCARD,
        context=orchestrator.context
    )
    
    return {
        "flashcards": response.data.get("flashcards") if response.data else None,
        "message": response.content
    }


@router.post("/medical/log")
async def log_clinical(
    procedure: str,
    rotation: str,
    supervisor: Optional[str] = None,
    hours: Optional[float] = None,
    notes: Optional[str] = None
):
    """Log a clinical procedure"""
    log_id = str(uuid4())
    return {
        "log_id": log_id,
        "procedure": procedure,
        "rotation": rotation,
        "logged_at": datetime.now().isoformat()
    }


# ============================================
# Business Endpoints
# ============================================

@router.get("/business/tenders")
async def list_tenders(status: Optional[str] = None):
    """List tracked tenders"""
    return {"tenders": [], "status": status}


@router.post("/business/invoice")
async def create_invoice(
    client_name: str,
    amount: float,
    currency: str = "KES",
    description: Optional[str] = None
):
    """Create an invoice"""
    invoice_id = str(uuid4())
    invoice_number = f"INV-{datetime.now().strftime('%Y%m')}-{invoice_id[:6].upper()}"
    
    return {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "client": client_name,
        "amount": amount,
        "currency": currency,
        "status": "draft"
    }


# ============================================
# Webhook Endpoints
# ============================================

@router.post("/webhooks/slack")
async def slack_webhook(request: Request, background_tasks: BackgroundTasks):
    """Slack events webhook"""
    data = await request.json()
    
    # Handle Slack URL verification
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}
    
    # Process in background
    async def process():
        response = await messaging.handle_incoming("slack", data)
        if response:
            event = data.get("event", {})
            channel_id = event.get("channel")
            thread_ts = event.get("thread_ts") or event.get("ts")
            
            if channel_id:
                from app.services.messaging import OutgoingMessage
                await messaging.slack.send_message(
                    OutgoingMessage(
                        channel="slack",
                        recipient_id=channel_id,
                        content=response,
                        reply_to=thread_ts
                    )
                )
    
    background_tasks.add_task(process)
    return {"status": "ok"}


@router.post("/webhooks/telegram")
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Telegram bot webhook"""
    data = await request.json()
    
    # Process in background
    async def process():
        response = await messaging.handle_incoming("telegram", data)
        if response:
            # Send response back
            chat_id = data.get("message", {}).get("chat", {}).get("id")
            if chat_id:
                from app.services.messaging import OutgoingMessage
                await messaging.telegram.send_message(
                    OutgoingMessage(
                        channel="telegram",
                        recipient_id=str(chat_id),
                        content=response
                    )
                )
    
    background_tasks.add_task(process)
    return {"status": "ok"}


@router.post("/webhooks/twilio")
async def twilio_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(None),
    NumMedia: str = Form("0")
):
    """Twilio (WhatsApp/SMS) webhook"""
    data = {
        "From": From,
        "Body": Body,
        "MessageSid": MessageSid,
        "NumMedia": NumMedia
    }
    
    # Determine channel
    channel = "whatsapp" if From.startswith("whatsapp:") else "sms"
    
    # Process in background
    async def process():
        response = await messaging.handle_incoming(channel, data)
        if response:
            from app.services.messaging import OutgoingMessage
            await messaging.twilio.send_message(
                OutgoingMessage(
                    channel=channel,
                    recipient_id=From,
                    content=response
                )
            )
    
    background_tasks.add_task(process)
    
    # Return TwiML response
    return PlainTextResponse(
        content='<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        media_type="application/xml"
    )


# ============================================
# Scheduler Endpoints
# ============================================

@router.get("/scheduler/upcoming")
async def upcoming_schedules(hours: int = 24):
    """Get upcoming scheduled events"""
    return {"upcoming": scheduler.get_upcoming(hours)}


@router.post("/scheduler/trigger/{rhythm_name}")
async def trigger_rhythm(rhythm_name: str):
    """Manually trigger a scheduled rhythm"""
    if rhythm_name not in scheduler.rhythms:
        raise HTTPException(status_code=404, detail=f"Rhythm {rhythm_name} not found")
    
    rhythm = scheduler.rhythms[rhythm_name]
    await scheduler._execute_rhythm(rhythm)
    
    return {"status": "triggered", "rhythm": rhythm_name}


# ============================================
# Memory/Context Endpoints
# ============================================

@router.get("/context")
async def get_current_context():
    """Get current orchestrator context"""
    return {
        "user_name": orchestrator.context.user_name,
        "timezone": orchestrator.context.timezone,
        "location_mode": orchestrator.context.location_mode,
        "is_trading_hours": orchestrator.context.is_trading_hours,
        "is_study_block": orchestrator.context.is_study_block,
        "current_time": orchestrator.context.current_time.isoformat(),
        "recent_intents": orchestrator.context.recent_intents[-5:]
    }


@router.post("/context/update")
async def update_context(updates: Dict[str, Any]):
    """Update orchestrator context"""
    orchestrator.update_context(**updates)
    return {"status": "updated", "context": updates}


# ============================================
# Notification Endpoints
# ============================================

@router.post("/notify")
async def send_notification(
    content: str,
    channel: str = "telegram",
    priority: str = "p2"
):
    """Send a notification"""
    success = await messaging.send(content, channel, priority=priority)
    return {"sent": success, "channel": channel, "priority": priority}


@router.post("/notify/priority")
async def send_priority_notification(content: str, priority: str = "p2"):
    """Send notification using priority-based channel selection"""
    success = await messaging.send_with_priority(content, priority)
    return {"sent": success, "priority": priority}
