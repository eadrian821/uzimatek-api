"""
JARVIS Configuration Module
Centralized configuration management with validation
"""

from functools import lru_cache
from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Application
    app_name: str = "JARVIS"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = Field(default="uzimatek-default-secret-key-change-in-prod!!")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    
    # Anthropic Claude model IDs
    anthropic_api_key: str
    claude_model_fast: str = "claude-haiku-4-5-20251001"  # Triage, classification, quick reads
    claude_model_balanced: str = "claude-sonnet-4-6"      # Analysis, synthesis, substantive ops
    claude_model_complex: str = "claude-opus-4-8"         # Architecture decisions, board prep
    claude_model_fable: str = "claude-fable-5"            # Clinical reasoning, coding, fraud detection
    
    # Embeddings — Voyage AI (medical domain optimized)
    voyage_api_key: Optional[str] = None
    voyage_model: str = "voyage-3-lite"   # Fast & accurate for medical text
    
    # Database — Supabase as single source of truth (required for SHA pipeline)
    supabase_url: str
    supabase_key: str
    supabase_service_key: Optional[str] = None
    # Postgres direct — only needed for JARVIS brain, not SHA pipeline
    database_url: Optional[str] = None

    # Redis — only needed for JARVIS brain scheduler/celery
    redis_url: Optional[str] = None

    # Qdrant — vector store for RAG (only needed for JARVIS brain)
    qdrant_url: Optional[str] = None
    qdrant_api_key: Optional[str] = None
    qdrant_collection: str = "jarvis_memory"
    # Medical-specific collections
    qdrant_medical_gold: str = "medical_gold_standard"
    qdrant_clinical_captures: str = "clinical_captures"
    qdrant_missed_findings: str = "missed_findings"
    qdrant_onenote: str = "onenote_annotations"
    qdrant_obsidian: str = "obsidian_notes"
    qdrant_recommendations: str = "medical_recommendations"
    
    # Twilio
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_whatsapp_number: Optional[str] = None
    twilio_sms_number: Optional[str] = None
    
    # Telegram — primary channel
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    # Slack — secondary channel (fixed two-way)
    slack_bot_token: Optional[str] = None
    slack_app_token: Optional[str] = None        # xapp-... for Socket Mode
    slack_signing_secret: Optional[str] = None   # For webhook verification
    slack_channel_id: Optional[str] = None
    
    # Google
    google_credentials_path: Optional[str] = None
    google_token_path: Optional[str] = None
    gmail_address: Optional[str] = None
    
    # Email (SMTP/IMAP)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    
    # Market Data
    alpha_vantage_api_key: Optional[str] = None

    # SHA Kenya Integration (Uzimatek)
    sha_uat_url: str = "https://api-uat.tiberbu.health"
    sha_facility_id: str = "DHABP00301"
    sha_org_id: str = "8TI-DHABP00301"
    sha_username: Optional[str] = None
    sha_password: Optional[str] = None
    sha_mock_mode: bool = False  # Set True when UAT is down — agents run with mock EBV

    # === MEDICAL BRAIN PATHS ===
    # Primary Obsidian vault (detected from system scan)
    obsidian_vault_path: str = r"C:\Users\eadri\Desktop\Dental\MyVault"
    # Medical corpus root — structured hierarchy under workspace
    medical_corpus_path: str = r"C:\jarvis\medical_corpus"
    # Audio inbox for Galaxy Watch/Buds → Whisper pipeline
    audio_inbox_path: str = r"C:\jarvis\audio_inbox"
    # Processed audio archive
    audio_archive_path: str = r"C:\jarvis\audio_archive"
    
    # OneNote local notebooks path
    onenote_path: str = r"C:\Users\eadri\Documents\OneNote Notebooks"
    
    # AnkiConnect
    ankiconnect_url: str = "http://localhost:8765"
    anki_default_deck: str = "JARVIS::Medical"
    anki_image_path: str = r"C:\Users\eadri\AppData\Roaming\Anki2\User 1\collection.media"
    
    # Whisper
    whisper_api_url: str = "http://localhost:9000"
    
    # Wikimedia Commons for dual-coding images
    wikimedia_api_url: str = "https://commons.wikimedia.org/w/api.php"
    
    # User
    user_name: str = "Adrian"
    user_timezone: str = "Africa/Nairobi"
    user_phone: Optional[str] = None
    user_whatsapp: Optional[str] = None
    user_email: Optional[str] = None
    
    # Location
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None
    mtrh_lat: Optional[float] = None
    mtrh_lng: Optional[float] = None
    
    # Feature Flags
    enable_trading_agent: bool = True
    enable_medical_agent: bool = True
    enable_business_agent: bool = True
    enable_voice: bool = False
    enable_whatsapp: bool = True
    enable_telegram: bool = True
    enable_slack: bool = True
    enable_medical_brain: bool = True
    
    # Monitoring
    sentry_dsn: Optional[str] = None
    log_level: str = "INFO"
    
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"
    
    @property
    def enabled_agents(self) -> List[str]:
        agents = ["pa"]  # PA is always enabled
        if self.enable_trading_agent:
            agents.append("trading")
        if self.enable_medical_agent:
            agents.append("medical")
        if self.enable_business_agent:
            agents.append("business")
        if self.enable_medical_brain:
            agents.extend(["delta", "atomization", "socratic", "crucible"])
        return agents


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export settings instance
settings = get_settings()
