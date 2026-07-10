"""Core form extraction logic."""

import logging
from typing import Dict, List, Optional
from datetime import datetime
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from bs4 import BeautifulSoup, Tag

from .models import (
    FormData,
    InputField,
    Button,
    ExtractionConfig,
    InputType,
    ButtonType,
)

logger = logging.getLogger(__name__)


class FormExtractionError(Exception):
    """Base exception for form extraction errors."""

    pass


class NetworkError(FormExtractionError):
    """Raised when network operations fail."""

    pass


class ParsingError(FormExtractionError):
    """Raised when HTML parsing fails."""

    pass


class FormExtractor:
    """Extract form elements from HTML pages with robust error handling."""

    # Input types to extract from form fields
    EXTRACTABLE_INPUT_TYPES = {
        InputType.TEXT.value,
        InputType.EMAIL.value,
        InputType.PASSWORD.value,
        InputType.DATE.value,
        InputType.TEL.value,
        InputType.NUMBER.value,
        InputType.URL.value,
        InputType.SEARCH.value,
        InputType.FILE.value,
        InputType.HIDDEN.value,
        InputType.CHECKBOX.value,
        InputType.RADIO.value,
        InputType.RANGE.value,
        InputType.COLOR.value,
    }

    def __init__(self, config: Optional[ExtractionConfig] = None) -> None:
        """Initialize the form extractor.

        Args:
            config: Extraction configuration. Defaults to ExtractionConfig().
        """
        self.config = config or ExtractionConfig()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic.

        Returns:
            Configured requests.Session with retry strategy.
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=self.config.max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def extract(self, url: str) -> FormData:
        """Extract form elements from a URL.

        Args:
            url: The URL to extract forms from.

        Returns:
            FormData object containing extracted elements.

        Raises:
            NetworkError: If the URL cannot be fetched.
            ParsingError: If HTML parsing fails.
        """
        logger.info(f"Starting form extraction from: {url}")

        try:
            html_content = self._fetch_url(url)
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch URL {url}: {e}")
            raise NetworkError(f"Failed to fetch URL: {e}") from e

        try:
            return self._parse_forms(url, html_content)
        except Exception as e:
            logger.error(f"Failed to parse HTML from {url}: {e}")
            raise ParsingError(f"Failed to parse HTML: {e}") from e

    def _fetch_url(self, url: str) -> str:
        """Fetch HTML content from URL with proper error handling.

        Args:
            url: The URL to fetch.

        Returns:
            HTML content as string.

        Raises:
            requests.exceptions.RequestException: On network errors.
        """
        headers = {"User-Agent": self.config.user_agent}
        response = self.session.get(
            url,
            headers=headers,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            allow_redirects=self.config.follow_redirects,
        )
        response.raise_for_status()
        logger.debug(f"Successfully fetched {url} (status: {response.status_code})")
        return response.text

    def _parse_forms(self, url: str, html_content: str) -> FormData:
        """Parse HTML and extract form elements.

        Args:
            url: Original URL (for context).
            html_content: HTML content as string.

        Returns:
            FormData object with extracted elements.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Build label mapping
        labels = self._build_label_map(soup)

        form_data = FormData(url=url, timestamp=datetime.utcnow().isoformat())

        # Try to find a form element
        form_tag = soup.find("form")
        if form_tag:
            form_data.form_id = form_tag.get("id")
            form_data.form_action = form_tag.get("action")
            form_data.form_method = (form_tag.get("method") or "GET").upper()

        # Extract input fields
        form_data.inputs = self._extract_inputs(soup, labels)
        logger.info(f"Extracted {len(form_data.inputs)} input fields")

        # Extract buttons
        form_data.buttons = self._extract_buttons(soup)
        logger.info(f"Extracted {len(form_data.buttons)} buttons")

        # Extract textarea if configured
        if self.config.include_textarea:
            textareas = self._extract_textareas(soup, labels)
            # Convert textareas to input fields for consistency
            form_data.inputs.extend(textareas)
            logger.info(f"Extracted {len(textareas)} textarea fields")

        # Extract select/option if configured
        if self.config.include_select:
            selects = self._extract_selects(soup, labels)
            form_data.inputs.extend(selects)
            logger.info(f"Extracted {len(selects)} select fields")

        logger.info(
            f"Form extraction complete: "
            f"{len(form_data.inputs)} fields, "
            f"{len(form_data.buttons)} buttons"
        )

        return form_data

    def _build_label_map(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Build a mapping of element IDs to their labels.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            Dictionary mapping element IDs to label text.
        """
        labels: Dict[str, str] = {}
        for label_tag in soup.find_all("label"):
            label_for = label_tag.get("for")
            if label_for:
                labels[label_for] = label_tag.get_text(strip=True)
        logger.debug(f"Built label map with {len(labels)} entries")
        return labels

    def _extract_inputs(
        self, soup: BeautifulSoup, labels: Dict[str, str]
    ) -> List[InputField]:
        """Extract input fields from the page.

        Args:
            soup: BeautifulSoup object of the page.
            labels: Pre-built label mapping.

        Returns:
            List of extracted InputField objects.
        """
        inputs: List[InputField] = []

        for input_tag in soup.find_all("input"):
            input_type = (input_tag.get("type") or "text").lower()

            # Skip certain types based on configuration
            if input_type == "hidden" and not self.config.extract_hidden_fields:
                continue
            if input_tag.get("disabled") and not self.config.extract_disabled_fields:
                continue

            # Skip submit/reset buttons (handled separately)
            if input_type in ["submit", "reset", "button"]:
                continue

            # Skip non-extractable types
            if input_type not in self.EXTRACTABLE_INPUT_TYPES:
                logger.debug(f"Skipping non-extractable input type: {input_type}")
                continue

            input_id = input_tag.get("id")
            input_name = input_tag.get("name")

            # Skip inputs without name
            if not input_name:
                logger.debug("Skipping input without name attribute")
                continue

            field = InputField(
                type=input_type,
                name=input_name,
                id=input_id,
                label=labels.get(input_id) if input_id else None,
                placeholder=input_tag.get("placeholder"),
                required=input_tag.has_attr("required"),
                disabled=input_tag.has_attr("disabled"),
                value=input_tag.get("value"),
                autocomplete=input_tag.get("autocomplete"),
                pattern=input_tag.get("pattern"),
                min=input_tag.get("min"),
                max=input_tag.get("max"),
                step=input_tag.get("step"),
            )
            inputs.append(field)

        return inputs

    def _extract_textareas(
        self, soup: BeautifulSoup, labels: Dict[str, str]
    ) -> List[InputField]:
        """Extract textarea fields from the page.

        Args:
            soup: BeautifulSoup object of the page.
            labels: Pre-built label mapping.

        Returns:
            List of extracted InputField objects for textareas.
        """
        textareas: List[InputField] = []

        for textarea_tag in soup.find_all("textarea"):
            if textarea_tag.get("disabled") and not self.config.extract_disabled_fields:
                continue

            textarea_id = textarea_tag.get("id")
            textarea_name = textarea_tag.get("name")

            if not textarea_name:
                continue

            field = InputField(
                type="textarea",
                name=textarea_name,
                id=textarea_id,
                label=labels.get(textarea_id) if textarea_id else None,
                placeholder=textarea_tag.get("placeholder"),
                required=textarea_tag.has_attr("required"),
                disabled=textarea_tag.has_attr("disabled"),
                value=textarea_tag.get_text(strip=True) or None,
            )
            textareas.append(field)

        return textareas

    def _extract_selects(
        self, soup: BeautifulSoup, labels: Dict[str, str]
    ) -> List[InputField]:
        """Extract select/option fields from the page.

        Args:
            soup: BeautifulSoup object of the page.
            labels: Pre-built label mapping.

        Returns:
            List of extracted InputField objects for selects.
        """
        selects: List[InputField] = []

        for select_tag in soup.find_all("select"):
            if select_tag.get("disabled") and not self.config.extract_disabled_fields:
                continue

            select_id = select_tag.get("id")
            select_name = select_tag.get("name")

            if not select_name:
                continue

            # Extract option values
            options = []
            for option_tag in select_tag.find_all("option"):
                option_value = option_tag.get("value", option_tag.get_text(strip=True))
                if option_value:
                    options.append(option_value)

            field = InputField(
                type="select",
                name=select_name,
                id=select_id,
                label=labels.get(select_id) if select_id else None,
                required=select_tag.has_attr("required"),
                disabled=select_tag.has_attr("disabled"),
                options=options,
            )
            selects.append(field)

        return selects

    def _extract_buttons(self, soup: BeautifulSoup) -> List[Button]:
        """Extract button elements from the page.

        Args:
            soup: BeautifulSoup object of the page.

        Returns:
            List of extracted Button objects.
        """
        buttons: List[Button] = []

        # Extract input[type=submit/reset/button]
        for input_tag in soup.find_all("input"):
            input_type = (input_tag.get("type") or "text").lower()
            if input_type not in ["submit", "reset", "button"]:
                continue

            button_type_map = {
                "submit": ButtonType.INPUT_SUBMIT.value,
                "reset": ButtonType.INPUT_RESET.value,
                "button": ButtonType.INPUT_BUTTON.value,
            }

            button = Button(
                type=button_type_map.get(input_type, ButtonType.INPUT_BUTTON.value),
                value=input_tag.get("value"),
                name=input_tag.get("name"),
                id=input_tag.get("id"),
                disabled=input_tag.has_attr("disabled"),
            )
            buttons.append(button)

        # Extract button tags
        for button_tag in soup.find_all("button"):
            button = Button(
                type=ButtonType.BUTTON_TAG.value,
                text=button_tag.get_text(strip=True),
                name=button_tag.get("name"),
                id=button_tag.get("id"),
                disabled=button_tag.has_attr("disabled"),
            )
            buttons.append(button)

        return buttons

    def close(self) -> None:
        """Close the session and clean up resources."""
        if self.session:
            self.session.close()
            logger.debug("Session closed")

    def __enter__(self) -> "FormExtractor":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
