"""Tests for form extraction core module."""

import pytest
from unittest.mock import patch, MagicMock

from form_extractor.core import (
    FormExtractor,
    FormExtractionError,
    NetworkError,
    ParsingError,
)
from form_extractor.models import ExtractionConfig, InputField, Button, FormData


class TestFormExtractor:
    """Test cases for FormExtractor class."""

    def test_initialization_with_default_config(self):
        """Test FormExtractor initializes with default config."""
        extractor = FormExtractor()
        assert extractor.config is not None
        assert extractor.config.timeout == 10
        assert extractor.session is not None

    def test_initialization_with_custom_config(self):
        """Test FormExtractor initializes with custom config."""
        config = ExtractionConfig(timeout=20, verify_ssl=False)
        extractor = FormExtractor(config)
        assert extractor.config.timeout == 20
        assert extractor.config.verify_ssl is False

    def test_context_manager(self):
        """Test FormExtractor works as context manager."""
        with FormExtractor() as extractor:
            assert extractor.session is not None
        # Session should be closed after context exit

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_simple_form(self, mock_get):
        """Test extraction of a simple form."""
        html = """
        <html>
            <form id="login-form" action="/login" method="POST">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required>
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
                <button type="submit">Login</button>
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        extractor = FormExtractor()
        result = extractor.extract("https://example.com/login")

        assert result.url == "https://example.com/login"
        assert result.form_id == "login-form"
        assert result.form_action == "/login"
        assert result.form_method == "POST"
        assert len(result.inputs) == 2
        assert len(result.buttons) == 1

        # Check email field
        email_field = result.inputs[0]
        assert email_field.type == "email"
        assert email_field.name == "email"
        assert email_field.label == "Email"
        assert email_field.required is True

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_with_various_input_types(self, mock_get):
        """Test extraction of various input types."""
        html = """
        <html>
            <form>
                <input type="text" name="text_field">
                <input type="email" name="email_field">
                <input type="number" name="number_field">
                <input type="date" name="date_field">
                <input type="tel" name="tel_field">
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        extractor = FormExtractor()
        result = extractor.extract("https://example.com")

        assert len(result.inputs) == 5
        input_types = [field.type for field in result.inputs]
        assert "text" in input_types
        assert "email" in input_types
        assert "number" in input_types

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_hidden_fields_excluded_by_default(self, mock_get):
        """Test that hidden fields are excluded by default."""
        html = """
        <html>
            <form>
                <input type="hidden" name="csrf_token" value="abc123">
                <input type="text" name="username">
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        extractor = FormExtractor()
        result = extractor.extract("https://example.com")

        # Only the text input should be extracted
        assert len(result.inputs) == 1
        assert result.inputs[0].name == "username"

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_hidden_fields_included_when_configured(self, mock_get):
        """Test that hidden fields are included when configured."""
        html = """
        <html>
            <form>
                <input type="hidden" name="csrf_token" value="abc123">
                <input type="text" name="username">
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        config = ExtractionConfig(extract_hidden_fields=True)
        extractor = FormExtractor(config)
        result = extractor.extract("https://example.com")

        assert len(result.inputs) == 2
        hidden_field = next(f for f in result.inputs if f.type == "hidden")
        assert hidden_field.value == "abc123"

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_textarea_fields(self, mock_get):
        """Test extraction of textarea fields."""
        html = """
        <html>
            <form>
                <label for="comment">Comment</label>
                <textarea id="comment" name="comment" required></textarea>
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        config = ExtractionConfig(include_textarea=True)
        extractor = FormExtractor(config)
        result = extractor.extract("https://example.com")

        assert len(result.inputs) == 1
        assert result.inputs[0].type == "textarea"
        assert result.inputs[0].name == "comment"

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_select_fields(self, mock_get):
        """Test extraction of select/option fields."""
        html = """
        <html>
            <form>
                <label for="country">Country</label>
                <select id="country" name="country" required>
                    <option value="">Select a country</option>
                    <option value="us">United States</option>
                    <option value="ca">Canada</option>
                </select>
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        config = ExtractionConfig(include_select=True)
        extractor = FormExtractor(config)
        result = extractor.extract("https://example.com")

        assert len(result.inputs) == 1
        select_field = result.inputs[0]
        assert select_field.type == "select"
        # Empty option value is skipped by the extractor
        assert len(select_field.options) == 2
        assert "us" in select_field.options
        assert "ca" in select_field.options

    @patch("form_extractor.core.requests.Session.get")
    def test_extract_buttons(self, mock_get):
        """Test extraction of buttons."""
        html = """
        <html>
            <form>
                <input type="submit" value="Submit">
                <input type="reset" value="Reset">
                <button type="button">Cancel</button>
            </form>
        </html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html
        mock_get.return_value = mock_response

        extractor = FormExtractor()
        result = extractor.extract("https://example.com")

        assert len(result.buttons) == 3
        types = [btn.type for btn in result.buttons]
        assert "input_submit" in types
        assert "input_reset" in types
        assert "button_tag" in types

    @patch("form_extractor.core.requests.Session.get")
    def test_network_error_handling(self, mock_get):
        """Test handling of network errors."""
        import requests

        mock_get.side_effect = requests.ConnectionError("Connection failed")

        extractor = FormExtractor()
        with pytest.raises(NetworkError):
            extractor.extract("https://example.com")

    @patch("form_extractor.core.requests.Session.get")
    def test_parsing_error_handling(self, mock_get):
        """Test handling of parsing errors."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Invalid HTML"
        mock_get.return_value = mock_response

        extractor = FormExtractor()
        # This should not raise an error, just return empty forms
        result = extractor.extract("https://example.com")
        assert result is not None


class TestFormData:
    """Test cases for FormData model."""

    def test_form_data_to_dict(self):
        """Test FormData serialization to dict."""
        form_data = FormData(
            url="https://example.com",
            form_id="test-form",
            form_action="/submit",
            form_method="POST",
        )

        result = form_data.to_dict()

        assert result["url"] == "https://example.com"
        assert result["form_id"] == "test-form"
        assert result["form_action"] == "/submit"
        assert result["form_method"] == "POST"

    def test_form_data_total_fields(self):
        """Test total_fields property."""
        form_data = FormData(url="https://example.com")
        form_data.inputs = [
            InputField(type="text", name="field1"),
            InputField(type="email", name="field2"),
        ]
        form_data.buttons = [Button(type="input_submit", value="Submit")]

        assert form_data.total_fields == 3

    def test_form_data_required_fields(self):
        """Test required_fields property."""
        form_data = FormData(url="https://example.com")
        form_data.inputs = [
            InputField(type="text", name="field1", required=True),
            InputField(type="email", name="field2", required=False),
        ]

        required = form_data.required_fields
        assert len(required) == 1
        assert required[0].name == "field1"


class TestExtractionConfig:
    """Test cases for ExtractionConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ExtractionConfig()

        assert config.timeout == 10
        assert config.verify_ssl is True
        assert config.extract_hidden_fields is False
        assert config.include_textarea is True
        assert config.include_select is True

    def test_config_to_dict(self):
        """Test config serialization."""
        config = ExtractionConfig(timeout=20, verify_ssl=False)
        result = config.to_dict()

        assert result["timeout"] == 20
        assert result["verify_ssl"] is False
