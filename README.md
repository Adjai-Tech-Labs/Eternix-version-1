# ETERNIX

An independent, agent-first AI system.

## Development environment

Activate the virtual environment:

    source .venv/bin/activate

Install the core dependencies:

    python -m pip install -e '.[core,development]'

Run checks:

    ruff check .
    pytest
