"""Public browser API schemas.

DTOs currently live in ``sombreado.domain.schemas`` so ``route_reads`` / ``advice``
can return them without depending on ``api``. This module is the HTTP-facing
re-export surface for routers.
"""

from sombreado.domain.schemas import (
    AdviceComputationRequest,
    AdviceHorizon,
    AdviceLocation,
    AdviceMode,
    AdvicePosition,
    AdviceRequest,
    AdviceResponse,
    AdviceSuccess,
    AdviceWithheld,
    DirectionChoice,
    DirectionChoicesResponse,
    LatLngPoint,
    RouteCandidate,
    RouteCandidatesResponse,
    RouteDirectionKind,
    RouteDirectionsResponse,
    RouteGeometryResponse,
)

__all__ = [
    "AdviceComputationRequest",
    "AdviceHorizon",
    "AdviceLocation",
    "AdviceMode",
    "AdvicePosition",
    "AdviceRequest",
    "AdviceResponse",
    "AdviceSuccess",
    "AdviceWithheld",
    "DirectionChoice",
    "DirectionChoicesResponse",
    "LatLngPoint",
    "RouteCandidate",
    "RouteCandidatesResponse",
    "RouteDirectionKind",
    "RouteDirectionsResponse",
    "RouteGeometryResponse",
]
