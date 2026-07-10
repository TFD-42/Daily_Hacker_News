"""
Form Extractor - Production-grade HTML form element extraction tool.

A robust, well-tested library for extracting and analyzing HTML form elements
from web pages, with comprehensive error handling and detailed metadata.
"""

__version__ = "1.0.0"
__author__ = "Daily Hacker News"
__license__ = "MIT"

from .core import FormExtractor, FormExtractionError
from .models import FormData, InputField, Button, ExtractionConfig

__all__ = [
    "FormExtractor",
    "FormExtractionError",
    "FormData",
    "InputField",
    "Button",
    "ExtractionConfig",
]
