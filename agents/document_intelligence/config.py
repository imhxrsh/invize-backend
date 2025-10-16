"""
Configuration for Document Intelligence Agent
Simple dotenv-based configuration without Pydantic Settings
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent.parent
AGENT_WORKSPACE = BASE_DIR / "agent_workspace"
UPLOADS_DIR = AGENT_WORKSPACE / "uploads"
TEMP_DIR = AGENT_WORKSPACE / "temp"

# Ensure directories exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# File processing limits
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
SUPPORTED_FORMATS = ["pdf", "png", "jpg", "jpeg", "tiff", "tif", "txt"]  # Added txt for testing

# OCR configuration
TESSERACT_LANGS = os.getenv("TESSERACT_LANGS", "eng")
PSM_DEFAULT = int(os.getenv("PSM_DEFAULT", "6"))  # Uniform block of text
OEM_DEFAULT = int(os.getenv("OEM_DEFAULT", "3"))  # Default OCR Engine Mode

# PDF processing
PDF_DPI = int(os.getenv("PDF_DPI", "300"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# LayoutLM configuration
USE_LAYOUTLM = os.getenv("USE_LAYOUTLM", "false").lower() == "true"
LAYOUTLM_MODEL = os.getenv("LAYOUTLM_MODEL", "microsoft/layoutlmv3-base")
LAYOUTLM_DEVICE = os.getenv("LAYOUTLM_DEVICE", "auto")  # 'cpu', 'cuda', or 'auto'
LAYOUTLM_TASK = os.getenv("LAYOUTLM_TASK", "token-classification")  # token-classification or sequence-classification
LAYOUTLM_CONFIDENCE_THRESHOLD = float(os.getenv("LAYOUTLM_CONFIDENCE_THRESHOLD", "0.5"))