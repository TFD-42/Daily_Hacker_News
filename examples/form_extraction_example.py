#!/usr/bin/env python3
"""
Form Extractor - Usage Examples

This script demonstrates various ways to use the Form Extractor library.
"""

import json
import logging
from form_extractor import FormExtractor, ExtractionConfig, NetworkError, ParsingError

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def example_1_basic_extraction():
    """Example 1: Basic form extraction with default configuration."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Form Extraction")
    print("=" * 60)

    try:
        extractor = FormExtractor()
        result = extractor.extract("https://example.com/login")

        print(f"\n✓ Extraction successful!")
        print(f"  URL: {result.url}")
        print(f"  Form ID: {result.form_id}")
        print(f"  Form Action: {result.form_action}")
        print(f"  Form Method: {result.form_method}")
        print(f"  Input Fields: {len(result.inputs)}")
        print(f"  Buttons: {len(result.buttons)}")

        # Print field details
        if result.inputs:
            print(f"\n  Input Fields:")
            for field in result.inputs:
                print(f"    - {field.name} ({field.type}): {field.label or 'no label'}")

        if result.buttons:
            print(f"\n  Buttons:")
            for button in result.buttons:
                print(f"    - {button.text or button.value or button.name} ({button.type})")

    except NetworkError as e:
        print(f"✗ Network error: {e}")
    except ParsingError as e:
        print(f"✗ Parsing error: {e}")


def example_2_custom_configuration():
    """Example 2: Extraction with custom configuration."""
    print("\n" + "=" * 60)
    print("Example 2: Custom Configuration")
    print("=" * 60)

    config = ExtractionConfig(
        timeout=20,
        verify_ssl=True,
        extract_hidden_fields=True,
        extract_disabled_fields=True,
        include_textarea=True,
        include_select=True,
        max_retries=5,
    )

    try:
        extractor = FormExtractor(config)
        result = extractor.extract("https://example.com/signup")

        print(f"\n✓ Extraction successful with custom config!")
        print(f"  Total fields (including hidden/disabled): {result.total_fields}")

        # Show hidden fields if any
        hidden_fields = [f for f in result.inputs if f.type == "hidden"]
        if hidden_fields:
            print(f"\n  Hidden Fields:")
            for field in hidden_fields:
                print(f"    - {field.name}: {field.value}")

    except (NetworkError, ParsingError) as e:
        print(f"✗ Error: {e}")


def example_3_context_manager():
    """Example 3: Using FormExtractor as a context manager."""
    print("\n" + "=" * 60)
    print("Example 3: Context Manager (Resource Cleanup)")
    print("=" * 60)

    try:
        # Context manager automatically closes the session
        with FormExtractor() as extractor:
            result = extractor.extract("https://example.com/contact")

            print(f"\n✓ Extraction in context manager successful!")
            print(f"  Total fields: {result.total_fields}")
            print(f"  Required fields: {len(result.required_fields)}")

            if result.required_fields:
                print(f"\n  Required Fields:")
                for field in result.required_fields:
                    print(f"    - {field.name} ({field.type}): {field.label or 'no label'}")

    except (NetworkError, ParsingError) as e:
        print(f"✗ Error: {e}")


def example_4_json_export():
    """Example 4: Extract and export form data as JSON."""
    print("\n" + "=" * 60)
    print("Example 4: JSON Export")
    print("=" * 60)

    try:
        extractor = FormExtractor()
        result = extractor.extract("https://example.com/register")

        # Convert to dictionary
        form_dict = result.to_dict()

        # Export as JSON
        json_output = json.dumps(form_dict, indent=2, ensure_ascii=False)
        print(f"\n✓ Form data exported as JSON:")
        print(json_output[:500] + "..." if len(json_output) > 500 else json_output)

    except (NetworkError, ParsingError) as e:
        print(f"✗ Error: {e}")


def example_5_batch_extraction():
    """Example 5: Extract forms from multiple URLs."""
    print("\n" + "=" * 60)
    print("Example 5: Batch Extraction")
    print("=" * 60)

    urls = [
        "https://example.com/login",
        "https://example.com/signup",
        "https://example.com/contact",
    ]

    config = ExtractionConfig(timeout=15)

    with FormExtractor(config) as extractor:
        results = []

        for url in urls:
            try:
                print(f"\nExtracting from: {url}")
                result = extractor.extract(url)
                results.append(
                    {
                        "url": result.url,
                        "fields": len(result.inputs),
                        "buttons": len(result.buttons),
                    }
                )
                print(f"  ✓ Found {result.total_fields} form elements")

            except (NetworkError, ParsingError) as e:
                print(f"  ✗ Failed: {e}")
                results.append({"url": url, "error": str(e)})

        # Summary
        print(f"\n✓ Batch extraction complete:")
        print(json.dumps(results, indent=2))


def example_6_field_analysis():
    """Example 6: Analyze form fields in detail."""
    print("\n" + "=" * 60)
    print("Example 6: Field Analysis")
    print("=" * 60)

    try:
        extractor = FormExtractor()
        result = extractor.extract("https://example.com/login")

        # Analyze input fields
        print(f"\n✓ Form Analysis:")
        print(f"\n  Field Type Distribution:")

        type_counts = {}
        for field in result.inputs:
            type_counts[field.type] = type_counts.get(field.type, 0) + 1

        for field_type, count in sorted(type_counts.items()):
            print(f"    - {field_type}: {count}")

        # Find required fields
        required = result.required_fields
        print(f"\n  Required Fields: {len(required)}/{len(result.inputs)}")
        for field in required:
            print(f"    - {field.name}: {field.label or 'no label'}")

        # Find fields with validation
        validated = [f for f in result.inputs if f.pattern or f.min or f.max]
        print(f"\n  Fields with Validation: {len(validated)}")
        for field in validated:
            print(f"    - {field.name}: ", end="")
            if field.pattern:
                print(f"pattern='{field.pattern}' ", end="")
            if field.min:
                print(f"min='{field.min}' ", end="")
            if field.max:
                print(f"max='{field.max}'", end="")
            print()

        # Find fields with autocomplete
        autocomplete_fields = [f for f in result.inputs if f.autocomplete]
        print(f"\n  Fields with Autocomplete: {len(autocomplete_fields)}")
        for field in autocomplete_fields:
            print(f"    - {field.name}: {field.autocomplete}")

    except (NetworkError, ParsingError) as e:
        print(f"✗ Error: {e}")


def example_7_error_handling():
    """Example 7: Comprehensive error handling."""
    print("\n" + "=" * 60)
    print("Example 7: Error Handling")
    print("=" * 60)

    test_urls = [
        ("https://example.com/login", "Valid URL"),
        ("https://invalid-url-that-does-not-exist.example/", "Invalid URL"),
        ("https://httpbin.org/status/500", "Server Error"),
    ]

    extractor = FormExtractor()

    for url, description in test_urls:
        print(f"\n  Testing: {description}")
        print(f"  URL: {url}")

        try:
            result = extractor.extract(url)
            print(f"  ✓ Success: {result.total_fields} form elements")

        except NetworkError as e:
            print(f"  ✗ Network Error: {e}")

        except ParsingError as e:
            print(f"  ✗ Parsing Error: {e}")

        except Exception as e:
            print(f"  ✗ Unexpected Error: {type(e).__name__}: {e}")

    extractor.close()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Form Extractor - Usage Examples")
    print("=" * 60)
    print("\nNote: These examples use example.com. In production,")
    print("replace with actual URLs containing forms.")

    # Uncomment the examples you want to run:

    # example_1_basic_extraction()
    # example_2_custom_configuration()
    # example_3_context_manager()
    # example_4_json_export()
    # example_5_batch_extraction()
    example_6_field_analysis()
    # example_7_error_handling()

    print("\n" + "=" * 60)
    print("Examples complete!")
    print("=" * 60)
