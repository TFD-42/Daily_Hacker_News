# Development Guide for Form Extractor

This guide covers development, testing, and contribution workflows for the Form Extractor library.

## Setup

### Prerequisites
- Python 3.9+
- git
- pip

### Development Environment

1. Clone the repository:
```bash
git clone https://github.com/TFD-42/Daily_Hacker_News.git
cd Daily_Hacker_News
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install development dependencies:
```bash
pip install -e ".[dev]"
```

## Project Structure

```
form_extractor/
├── __init__.py           # Package exports
├── cli.py                # Command-line interface
├── core.py               # Core extraction logic
├── models.py             # Data models and enums
├── README.md             # User documentation
└── DEVELOPMENT.md        # This file

tests/
└── test_form_extractor.py  # Unit tests

examples/
└── form_extraction_example.py  # Usage examples
```

## Code Style

The project follows PEP 8 and uses:
- **black** for code formatting
- **isort** for import sorting
- **ruff** for linting
- **mypy** for type checking

### Format code
```bash
black form_extractor/ tests/
isort form_extractor/ tests/
```

### Check code quality
```bash
ruff check form_extractor/ tests/
mypy form_extractor/
```

## Testing

### Run all tests
```bash
pytest
```

### Run with coverage
```bash
pytest --cov=form_extractor --cov-report=html
```

### Run specific test
```bash
pytest tests/test_form_extractor.py::TestFormExtractor::test_extract_simple_form
```

### Run with markers
```bash
# Skip network tests
pytest -m "not network"

# Run only slow tests
pytest -m "slow"
```

### Test structure

Each test class focuses on a specific component:
- `TestFormExtractor`: Core extraction functionality
- `TestFormData`: Data model serialization
- `TestExtractionConfig`: Configuration handling

Tests use mocking to avoid network calls and external dependencies.

## Key Concepts

### Error Handling

The library defines custom exceptions:
- `FormExtractionError`: Base exception
- `NetworkError`: Network-related failures
- `ParsingError`: HTML parsing failures

All exceptions should include descriptive error messages for debugging.

### Logging

Uses Python's built-in `logging` module:
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Include context information (URLs, field counts, etc.)
- Use named loggers: `logger = logging.getLogger(__name__)`

### Type Hints

All functions and methods must have type hints:
```python
def extract(self, url: str) -> FormData:
    """Extract form elements from a URL."""
    ...
```

### Configuration

Use `ExtractionConfig` for all configurable options:
- Never hardcode values that should be configurable
- Provide sensible defaults
- Document all configuration options

## Adding Features

### Adding a new field type

1. Add to `InputType` enum in `models.py`:
```python
class InputType(str, Enum):
    MY_TYPE = "my_type"
```

2. Add to `EXTRACTABLE_INPUT_TYPES` in `core.py`:
```python
EXTRACTABLE_INPUT_TYPES = {
    ...
    InputType.MY_TYPE.value,
    ...
}
```

3. Update `_extract_inputs()` method if special handling needed

4. Add tests in `tests/test_form_extractor.py`

### Adding a new configuration option

1. Add to `ExtractionConfig` in `models.py`:
```python
@dataclass
class ExtractionConfig:
    my_option: bool = False
```

2. Use in `FormExtractor` methods
3. Add CLI argument in `cli.py` if user-facing
4. Add tests for the new option
5. Update documentation

## Debugging

### Enable verbose logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Use pdb for debugging
```python
import pdb; pdb.set_trace()
```

### Inspect extracted data
```python
import json
result = extractor.extract(url)
print(json.dumps(result.to_dict(), indent=2))
```

## Performance Considerations

- Use context manager to reuse session across multiple URLs
- Retry logic with exponential backoff prevents hammering servers
- Timeout protection prevents hanging connections
- BeautifulSoup is memory-efficient for typical HTML pages

## Security

- SSL certificate verification enabled by default
- Timeout protection against slow loris attacks
- No code execution or unsafe parsing
- HTML parser doesn't execute embedded scripts

## Common Issues

### ImportError: No module named 'form_extractor'
Solution: Install in development mode: `pip install -e .`

### SSL: CERTIFICATE_VERIFY_FAILED
Solution: Either:
- Fix SSL certificates on your system
- Use `--no-verify-ssl` flag (not recommended for production)
- Update CA bundle: `pip install -U certifi`

### Connection timeouts
Solution: Increase timeout in config:
```python
config = ExtractionConfig(timeout=30)
```

### Memory usage on large pages
Solution: The library should handle large pages efficiently. If issues persist:
- Check if the page is actually that large
- Monitor with memory profiler: `pip install memory-profiler`

## Releasing

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Run full test suite: `pytest --cov`
4. Create git tag: `git tag v1.0.0`
5. Push to repository: `git push && git push --tags`
6. Build distribution: `python -m build`
7. Upload to PyPI: `twine upload dist/*`

## Documentation

- Docstrings use Google style format
- All public methods must have docstrings
- Include examples in README
- Keep DEVELOPMENT.md updated
- Add type hints (they serve as documentation)

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

## Support

For questions or issues:
1. Check existing GitHub issues
2. Enable debug logging to diagnose problems
3. Create detailed issue report with:
   - Python version
   - Library version
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant error logs

## Resources

- Python logging: https://docs.python.org/3/library/logging.html
- BeautifulSoup4: https://www.crummy.com/software/BeautifulSoup/
- Requests: https://requests.readthedocs.io/
- Pytest: https://docs.pytest.org/
- Type hints: https://docs.python.org/3/library/typing.html
