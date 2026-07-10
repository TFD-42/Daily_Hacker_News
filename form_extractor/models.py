"""Data models for form extraction."""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class InputType(str, Enum):
    """Supported HTML input types for extraction."""

    TEXT = "text"
    EMAIL = "email"
    PASSWORD = "password"
    DATE = "date"
    TEL = "tel"
    NUMBER = "number"
    URL = "url"
    SEARCH = "search"
    HIDDEN = "hidden"
    FILE = "file"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    RANGE = "range"
    COLOR = "color"


class ButtonType(str, Enum):
    """Button element types."""

    INPUT_SUBMIT = "input_submit"
    INPUT_BUTTON = "input_button"
    INPUT_RESET = "input_reset"
    BUTTON_TAG = "button_tag"


@dataclass
class InputField:
    """Represents an extracted HTML input field."""

    type: str
    name: str
    id: Optional[str] = None
    label: Optional[str] = None
    placeholder: Optional[str] = None
    required: bool = False
    disabled: bool = False
    value: Optional[str] = None
    autocomplete: Optional[str] = None
    pattern: Optional[str] = None
    min: Optional[str] = None
    max: Optional[str] = None
    step: Optional[str] = None
    options: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class Button:
    """Represents an extracted button element."""

    type: str
    text: Optional[str] = None
    name: Optional[str] = None
    id: Optional[str] = None
    value: Optional[str] = None
    disabled: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class FormData:
    """Container for extracted form data."""

    url: str
    inputs: List[InputField] = field(default_factory=list)
    buttons: List[Button] = field(default_factory=list)
    form_id: Optional[str] = None
    form_action: Optional[str] = None
    form_method: str = "GET"
    timestamp: Optional[str] = None
    extraction_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "form_id": self.form_id,
            "form_action": self.form_action,
            "form_method": self.form_method,
            "timestamp": self.timestamp,
            "inputs": [field.to_dict() for field in self.inputs],
            "buttons": [btn.to_dict() for btn in self.buttons],
            "extraction_errors": self.extraction_errors,
        }

    @property
    def total_fields(self) -> int:
        """Get total number of form fields."""
        return len(self.inputs) + len(self.buttons)

    @property
    def required_fields(self) -> List[InputField]:
        """Get list of required input fields."""
        return [field for field in self.inputs if field.required]


@dataclass
class ExtractionConfig:
    """Configuration for form extraction."""

    timeout: int = 10
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
    extract_hidden_fields: bool = False
    extract_disabled_fields: bool = False
    max_retries: int = 3
    verify_ssl: bool = True
    follow_redirects: bool = True
    include_textarea: bool = True
    include_select: bool = True

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
