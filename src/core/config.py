from pydantic import BaseModel, Field
import os
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    app_name: str = "OmniGuard AI - Hybrid Fraud & Customer Resolution Engine"
    app_version: str = "0.1.0"
    app_env: str = os.getenv("APP_ENV", "development")
    debug: bool = os.getenv("DEBUG", "True").lower() == "true"
    port: int = int(os.getenv("APP_PORT", "8000"))
    
    # LLM Settings
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    
    # Decision Thresholds (Production Thinking Trade-offs)
    fraud_risk_high_threshold: float = float(os.getenv("FRAUD_RISK_HIGH_THRESHOLD", "0.85"))
    fraud_risk_medium_threshold: float = float(os.getenv("FRAUD_RISK_MEDIUM_THRESHOLD", "0.50"))
    hitl_confidence_threshold: float = float(os.getenv("HITL_CONFIDENCE_THRESHOLD", "0.70"))
    max_autonomous_transaction_limit: float = float(os.getenv("MAX_AUTONOMOUS_TRANSACTION_LIMIT", "500.0"))

settings = Settings()
