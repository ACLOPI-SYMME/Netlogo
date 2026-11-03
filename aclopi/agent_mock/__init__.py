"""Mock of the agent service (L5.5): POST /decide, GET /health. Run with `python -m aclopi.agent_mock`."""

from aclopi.agent_mock.app import MockConfig, create_mock_app

__all__ = ["MockConfig", "create_mock_app"]
