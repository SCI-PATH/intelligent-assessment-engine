"""HTTP clients for peer microservices (C1 / C3 / C4)."""

from iae.infrastructure.clients.peers import (
    Component1Client,
    Component3Client,
    Component4Client,
    mock_assessment_submit,
    mock_bkt_snapshot,
)

__all__ = [
    "Component1Client",
    "Component3Client",
    "Component4Client",
    "mock_assessment_submit",
    "mock_bkt_snapshot",
]
