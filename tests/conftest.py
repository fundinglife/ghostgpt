"""
Pytest configuration for CustomGPTs tests.

Registers custom markers:
    slow: Tests that hit actual ChatGPT (10-60s each, require logged-in session)

Usage:
    pytest tests/ -v                    # Run all tests
    pytest tests/ -v -m "not slow"      # Skip slow ChatGPT tests
    pytest tests/ -v -m slow            # Only run ChatGPT tests
"""


def pytest_configure(config):
    """Register custom pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests that hit actual ChatGPT (slow, requires login)"
    )
