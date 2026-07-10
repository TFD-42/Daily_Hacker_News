"""Command-line interface for form extraction."""

import sys
import json
import logging
import argparse
from pathlib import Path
from typing import Optional

from .core import FormExtractor, FormExtractionError
from .models import ExtractionConfig

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def setup_logging(verbose: bool, quiet: bool) -> None:
    """Configure logging level based on CLI flags.

    Args:
        verbose: Enable verbose (DEBUG) logging.
        quiet: Disable logging output.
    """
    root_logger = logging.getLogger()
    if quiet:
        root_logger.setLevel(logging.CRITICAL)
    elif verbose:
        root_logger.setLevel(logging.DEBUG)
    else:
        root_logger.setLevel(logging.INFO)


def create_parser() -> argparse.ArgumentParser:
    """Create and return the argument parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="form-extractor",
        description="Extract HTML form elements from web pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  form-extractor https://example.com/form
  form-extractor https://example.com --output forms.json
  form-extractor https://example.com --timeout 20 --no-verify-ssl
  form-extractor https://example.com --include-hidden --include-disabled
        """,
    )

    parser.add_argument(
        "url",
        help="URL of the page to extract forms from",
    )

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output file (JSON). If not provided, prints to stdout",
    )

    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )

    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL certificate verification",
    )

    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden input fields",
    )

    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Include disabled input fields",
    )

    parser.add_argument(
        "--no-textarea",
        action="store_true",
        help="Exclude textarea fields",
    )

    parser.add_argument(
        "--no-select",
        action="store_true",
        help="Exclude select fields",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of retries for failed requests (default: 3)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress all logging output except errors",
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 1.0.0",
    )

    return parser


def main(argv: Optional[list] = None) -> int:
    """Main entry point for CLI.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    parser = create_parser()
    args = parser.parse_args(argv)

    # Setup logging
    setup_logging(args.verbose, args.quiet)

    # Create extraction config
    config = ExtractionConfig(
        timeout=args.timeout,
        verify_ssl=not args.no_verify_ssl,
        extract_hidden_fields=args.include_hidden,
        extract_disabled_fields=args.include_disabled,
        include_textarea=not args.no_textarea,
        include_select=not args.no_select,
        max_retries=args.retries,
    )

    try:
        logger.info(f"Extracting forms from: {args.url}")

        with FormExtractor(config) as extractor:
            form_data = extractor.extract(args.url)

        result = form_data.to_dict()

        # Output results
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            logger.info(f"Results saved to: {output_path}")
            print(f"✓ Extraction complete. Results saved to {output_path}", file=sys.stderr)
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))

        return 0

    except FormExtractionError as e:
        logger.error(f"Extraction failed: {e}")
        print(f"✗ Error: {e}", file=sys.stderr)
        return 1

    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        print("✗ Cancelled", file=sys.stderr)
        return 130

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"✗ Unexpected error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
