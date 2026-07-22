"""
JARVIS Database Models
SQLAlchemy models for all domains
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, 
    ForeignKey, JSON, Enum as SQLEnum, Index
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.sql import func
import uuid
import enum

Base = declarative_base()


# ============================================
# Enums
# ============================================

class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"

class TaskPriority(str, enum.Enum):
    P0_CRITICAL = "p0"
    P1_URGENT = "p1"
    P2_NORMAL = "p2"
    P3_LOW = "p3"

class NotificationPriority(str, enum.Enum):
    P0_CRITICAL = "p0"
    P1_URGENT = "p1"
    P2_NORMAL = "p2"
    P3_LOW = "p3"

class Domain(str, enum.Enum):
    MEDICAL = "medical"
    TRADING = "trading"
    BUSINESS = "business"
    PA = "pa"
    PERSONAL = "personal"

class LocationMode(str, enum.Enum):
    CLINICAL = "clinical"
    FULL_SPECTRUM = "full_spectrum"
    US_CLINICAL = "us_clinical"
    LIGHT_TOUCH = "light_touch"
    MINIMAL = "minimal"

class TradeDirection(str, enum.Enum):
    LONG = "long"
    SHORT = "short"

class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# ============================================
# Base Mixin
# ============================================

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps"""
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# ============================================
# User & Context Models
# ============================================

class UserProfile(Base, TimestampMixin):
    __tablename__ = "user_profiles"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    timezone = Column(String(50), default="Africa/Nairobi")
    location_mode = Column(SQLEnum(LocationMode), default=LocationMode.FULL_SPECTRUM)
    preferences = Column(JSON, default={})
    active_roles = Column(ARRAY(String), default=["medical_student", "entrepreneur", "trader"])
    
    # Relationships
    context_states = relationship("ContextState", back_populates="user")
    tasks = relationship("Task", back_populates="user")


class ContextState(Base, TimestampMixin):
    __tablename__ = "context_states"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False)
    
    # Location
    latitude = Column(Float)
    longitude = Column(Float)
    resolved_name = Column(String(255))
    mode = Column(SQLEnum(LocationMode), default=LocationMode.FULL_SPECTRUM)
    
    # Time context
    local_time = Column(DateTime(timezone=True))
    is_trading_hours = Column(Boolean, default=False)
    is_study_block = Column(Boolean, default=False)
    
    # Energy
    sleep_score = Column(Float)
    hours_since_break = Column(Float)
    focus_duration_minutes = Column(Integer)
    
    # Active state
    active_task_ids = Column(ARRAY(UUID(as_uuid=True)), default=[])
    current_domain = Column(SQLEnum(Domain))
    
    # Raw state JSON for flexibility
    state_json = Column(JSON, default={})
    
    # Relationships
    user = relationship("UserProfile", back_populates="context_states")


class MemoryEpisodic(Base, TimestampMixin):
    __tablename__ = "memory_episodic"
    __table_args__ = (
        Index("idx_memory_episodic_domain", "domain"),
        Index("idx_memory_episodic_timestamp", "timestamp"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain = Column(SQLEnum(Domain), nullable=False)
    event_type = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    outcome = Column(Text)
    embedding_id = Column(String(255))  # Reference to Qdrant vector
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    meta_data = Column(JSON, default={})


class MemorySemantic(Base, TimestampMixin):
    __tablename__ = "memory_semantic"
    __table_args__ = (
        Index("idx_memory_semantic_category_key", "category", "key"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(100), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    source = Column(String(255))
    last_validated = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# Medical Domain Models
# ============================================

class ClinicalLog(Base, TimestampMixin):
    __tablename__ = "clinical_logs"
    __table_args__ = (
        Index("idx_clinical_logs_date", "date"),
        Index("idx_clinical_logs_rotation", "rotation"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True), nullable=False)
    rotation = Column(String(100), nullable=False)  # e.g., "ENT", "Ortho", "Trauma"
    procedure = Column(String(255), nullable=False)
    supervisor = Column(String(255))
    notes = Column(Text)
    hours = Column(Float)
    tags = Column(ARRAY(String), default=[])
    location = Column(String(100))  # MTRH, LA, etc.


class StudySession(Base, TimestampMixin):
    __tablename__ = "study_sessions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic = Column(String(255), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    cards_reviewed = Column(Integer, default=0)
    accuracy = Column(Float)
    weak_areas = Column(JSON, default=[])
    session_date = Column(DateTime(timezone=True), server_default=func.now())


class FlashcardDeck(Base, TimestampMixin):
    __tablename__ = "flashcard_decks"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    source_doc = Column(String(500))
    card_count = Column(Integer, default=0)
    last_reviewed = Column(DateTime(timezone=True))
    performance = Column(JSON, default={})
    tags = Column(ARRAY(String), default=[])


class LiteratureQueue(Base, TimestampMixin):
    __tablename__ = "literature_queue"
    __table_args__ = (
        Index("idx_literature_queue_status", "status"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    authors = Column(Text)
    source = Column(String(255))  # PubMed, Journal name, etc.
    pubmed_id = Column(String(50))
    doi = Column(String(100))
    url = Column(String(500))
    relevance_score = Column(Float, default=0.5)
    status = Column(String(50), default="queued")  # queued, reading, read, skipped
    summary = Column(Text)
    added_date = Column(DateTime(timezone=True), server_default=func.now())
    read_date = Column(DateTime(timezone=True))


# ============================================
# Business Domain Models
# ============================================

class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (
        Index("idx_contacts_domain", "domain"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    organization = Column(String(255))
    role = Column(String(255))
    domain = Column(SQLEnum(Domain))
    email = Column(String(255))
    phone = Column(String(50))
    whatsapp = Column(String(50))
    relationship_score = Column(Float, default=0.5)  # 0-1
    last_contact = Column(DateTime(timezone=True))
    tags = Column(ARRAY(String), default=[])
    notes = Column(Text)


class Tender(Base, TimestampMixin):
    __tablename__ = "tenders"
    __table_args__ = (
        Index("idx_tenders_deadline", "deadline"),
        Index("idx_tenders_status", "status"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(255), nullable=False)  # KEMSA, County, etc.
    title = Column(String(500), nullable=False)
    description = Column(Text)
    deadline = Column(DateTime(timezone=True))
    value = Column(Float)
    currency = Column(String(10), default="KES")
    status = Column(String(50), default="identified")  # identified, analyzing, applying, submitted, won, lost
    match_score = Column(Float, default=0.5)
    url = Column(String(500))
    documents = Column(JSON, default=[])
    notes = Column(Text)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_due_date", "due_date"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_number = Column(String(50), nullable=False, unique=True)
    client_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id"))
    client_name = Column(String(255))
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="KES")
    status = Column(String(50), default="draft")  # draft, sent, paid, overdue, cancelled
    payment_method = Column(String(50))  # M-Pesa, Bank, Cash
    due_date = Column(DateTime(timezone=True))
    paid_date = Column(DateTime(timezone=True))
    items = Column(JSON, default=[])
    notes = Column(Text)
    
    # Relationships
    client = relationship("Contact")


class IncomeStream(Base, TimestampMixin):
    __tablename__ = "income_streams"
    __table_args__ = (
        Index("idx_income_streams_date", "date"),
        Index("idx_income_streams_source_type", "source_type"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String(100), nullable=False)  # consulting, tutoring, technical_writing, visa_coaching
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="KES")
    date = Column(DateTime(timezone=True), nullable=False)
    category = Column(String(100))
    notes = Column(Text)
    invoice_id = Column(UUID(as_uuid=True), ForeignKey("invoices.id"))


class UzimatekRoadmap(Base, TimestampMixin):
    __tablename__ = "uzimatek_roadmap"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feature = Column(String(255), nullable=False)
    description = Column(Text)
    sprint = Column(String(50))
    status = Column(String(50), default="backlog")  # backlog, in_progress, review, done
    priority = Column(SQLEnum(TaskPriority), default=TaskPriority.P2_NORMAL)
    assignee = Column(String(100))
    dependencies = Column(ARRAY(UUID(as_uuid=True)), default=[])
    due_date = Column(DateTime(timezone=True))


# ============================================
# Trading Domain Models
# ============================================

class Trade(Base, TimestampMixin):
    __tablename__ = "trades"
    __table_args__ = (
        Index("idx_trades_symbol", "symbol"),
        Index("idx_trades_entry_time", "entry_time"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    market = Column(String(50))  # NSE, NYSE, FOREX, CRYPTO
    direction = Column(SQLEnum(TradeDirection), nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    quantity = Column(Float, nullable=False)
    pnl = Column(Float)
    pnl_percentage = Column(Float)
    strategy = Column(String(100))
    timeframe = Column(String(20))
    emotional_state = Column(String(100))
    entry_time = Column(DateTime(timezone=True), nullable=False)
    exit_time = Column(DateTime(timezone=True))
    notes = Column(Text)
    tags = Column(ARRAY(String), default=[])
    screenshots = Column(JSON, default=[])


class Watchlist(Base, TimestampMixin):
    __tablename__ = "watchlist"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    market = Column(String(50))
    alert_levels = Column(JSON, default={})  # {"support": [], "resistance": [], "targets": []}
    thesis = Column(Text)
    timeframe = Column(String(20))
    active = Column(Boolean, default=True)


class Portfolio(Base, TimestampMixin):
    __tablename__ = "portfolios"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)  # "Personal", "Sandrah"
    owner = Column(String(100))
    positions = Column(JSON, default=[])
    total_value = Column(Float)
    currency = Column(String(10), default="USD")
    last_updated = Column(DateTime(timezone=True))


class MarketBrief(Base, TimestampMixin):
    __tablename__ = "market_briefs"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    date = Column(DateTime(timezone=True), nullable=False)
    brief_type = Column(String(50), nullable=False)  # morning, evening, flash
    content = Column(Text, nullable=False)
    markets_covered = Column(ARRAY(String), default=[])
    key_levels = Column(JSON, default={})


class Signal(Base, TimestampMixin):
    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_symbol", "symbol"),
        Index("idx_signals_generated_at", "generated_at"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol = Column(String(20), nullable=False)
    signal_type = Column(String(50), nullable=False)  # entry, exit, alert
    direction = Column(SQLEnum(TradeDirection))
    timeframe = Column(String(20))
    confidence = Column(Float)
    price_at_signal = Column(Float)
    target_price = Column(Float)
    stop_loss = Column(Float)
    outcome = Column(String(50))  # win, loss, pending, expired
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    analysis = Column(JSON, default={})


# ============================================
# PA Operations Models
# ============================================

class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_due_date", "due_date"),
        Index("idx_tasks_domain", "domain"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("user_profiles.id"))
    title = Column(String(500), nullable=False)
    description = Column(Text)
    domain = Column(SQLEnum(Domain), default=Domain.PA)
    priority = Column(SQLEnum(TaskPriority), default=TaskPriority.P2_NORMAL)
    status = Column(SQLEnum(TaskStatus), default=TaskStatus.PENDING)
    due_date = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    depends_on = Column(ARRAY(UUID(as_uuid=True)), default=[])
    recurrence = Column(JSON)  # {"type": "daily|weekly|monthly", "interval": 1, ...}
    tags = Column(ARRAY(String), default=[])
    
    # Relationships
    user = relationship("UserProfile", back_populates="tasks")


class Communication(Base, TimestampMixin):
    __tablename__ = "communications"
    __table_args__ = (
        Index("idx_communications_channel", "channel"),
        Index("idx_communications_status", "status"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel = Column(String(50), nullable=False)  # whatsapp, telegram, sms, email
    direction = Column(String(10), nullable=False)  # inbound, outbound
    contact_id = Column(UUID(as_uuid=True), ForeignKey("contacts.id"))
    contact_identifier = Column(String(255))  # phone number or email
    content = Column(Text, nullable=False)
    status = Column(String(50), default="draft")  # draft, sent, delivered, read, failed
    scheduled_at = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    external_id = Column(String(255))  # Twilio SID, etc.


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("idx_notifications_priority", "priority"),
        Index("idx_notifications_delivered", "delivered"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    priority = Column(SQLEnum(NotificationPriority), nullable=False)
    channel = Column(String(50))  # whatsapp, telegram, sms, watch, dashboard
    title = Column(String(255))
    content = Column(Text, nullable=False)
    domain = Column(SQLEnum(Domain))
    delivered = Column(Boolean, default=False)
    delivered_at = Column(DateTime(timezone=True))
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True))
    snoozed_until = Column(DateTime(timezone=True))
    action_url = Column(String(500))
    meta_data = Column(JSON, default={})


class DailyRhythm(Base, TimestampMixin):
    __tablename__ = "daily_rhythms"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    time_slot = Column(String(10), nullable=False)  # HH:MM format
    action = Column(String(100), nullable=False)
    description = Column(Text)
    enabled = Column(Boolean, default=True)
    channels = Column(ARRAY(String), default=["whatsapp"])
    days_of_week = Column(ARRAY(Integer), default=[0,1,2,3,4,5,6])  # 0=Monday
    override_conditions = Column(JSON, default={})


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("idx_approvals_status", "status"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action_type = Column(String(100), nullable=False)  # trade_execution, payment, email_send
    title = Column(String(255), nullable=False)
    details = Column(JSON, nullable=False)
    status = Column(SQLEnum(ApprovalStatus), default=ApprovalStatus.PENDING)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True))
    approved_at = Column(DateTime(timezone=True))
    approved_via = Column(String(50))  # whatsapp, telegram, dashboard, biometric
    notes = Column(Text)


# ============================================
# Conversation History
# ============================================

class ConversationMessage(Base, TimestampMixin):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        Index("idx_conversation_messages_session", "session_id"),
    )
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(100), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    channel = Column(String(50))
    agent = Column(String(50))  # which agent handled this
    tokens_used = Column(Integer)
    meta_data = Column(JSON, default={})
