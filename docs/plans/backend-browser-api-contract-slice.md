# Backend Browser API Contract Slice

## Summary

Implement the frontend-owned v1 browser contract in `sombreado-service` as the public API, replacing the current route-summary/advisory public shapes rather than running dual contracts.

This document is the authoritative contract slice for implementation. Older detailed plans under `docs/superpowers/plans/` must be synced or rewritten from this document before execution.

The new public language is `Route Candidate`, `Direction Choice`, `Route Geometry`, and `Advice`. Update `CONTEXT.md` accordingly, and add an ADR because this is a deliberate public-contract pivot from backend-owned route summaries to frontend-owned rider-flow endpoints.

## Key Changes

- Replace public route discovery with:
  - `GET /v1/route-candidates/nearby?lat&lng&radiusMeters&limit`
  - `GET /v1/route-candidates/search?query&limit`
  - Nearby defaults: `radiusMeters=1200`, `limit=5`
  - Search default: `limit=8`
  - Replace the old shared `nearby_radius_meters=100` and `nearby_limit=10` defaults with contract-specific settings such as `route_candidate_nearby_radius_meters`, `route_candidate_nearby_limit`, and `route_candidate_search_limit`.
  - Candidate payloads are route-only: `routeId`, `routeVersionId`, `routeCode`, `routeName`, optional `distanceMeters`, and `directionHints`.
  - Each route candidate represents one current route/current route-version pair; group candidate queries by route and route version rather than merging multiple current-version rows.
  - `directionHints` are ordered departure labels aggregated from current route directions; no direction IDs or route direction names appear in candidates.
  - De-duplicate `directionHints` while preserving first direction-sequence/departure-label order.
  - Map `service_directions.sequence` and `service_directions.confidence` in `sombreado-service`; use route direction sequence first and service direction sequence second when ordering candidate hints and direction-choice `departureLabels`.
  - Expose departure labels only from service directions with `confidence in ("high", "medium")` and non-null `route_direction_id`; low-confidence and unmatched labels stay out of public route candidates and direction choices.
  - Do not use departure-label presence as direction usability. A valid current direction with no public labels remains a direction choice with `departureLabels: []`.
  - `distanceMeters` for nearby candidates is the nearest current segment geometry distance for the route, independent of departure-label confidence.
  - Manual search may return current route candidates with `directionHints: []`; the direction endpoint then returns `200 { "directions": [] }`.
  - Nearby candidates require current segment geometry close enough to compute meaningful `distanceMeters`; do not return geometry-less routes from nearby discovery.
- Replace direction and geometry public surfaces with:
  - `GET /v1/routes/{routeId}/directions?routeVersionId=...`
  - `GET /v1/routes/{routeId}/directions/{routeDirectionId}/geometry?routeVersionId=...`
  - Direction choices return authoritative `routeDirectionId`, `sequence`, `name`, and `departureLabels`.
  - Geometry returns `{ routeId, routeVersionId, routeDirectionId, polyline }`, flattening ordered segment LineStrings into `{lat,lng}` points and removing adjacent duplicate joins.
  - Valid current route/version/direction rows with no materialized segment geometry return `200` and `polyline: []`; invalid route/version/direction identifiers still use the public error envelope.
- Replace public advice with:
  - `POST /v1/advice`
  - Request supports `mode`, `horizon`, top-level `observedAt`, optional `location`, and `fallbackToPreview`.
  - Support all four `mode` + `horizon` combinations.
  - `horizon` selects exactly one computation window; do not return both upcoming and remaining-route windows in one advice response.
  - `mode: "onboard"` requires `location`; missing or invalid location returns `422 validationFailed`.
  - `mode: "preview"` must not include `location`; reject preview requests with a location as `422 validationFailed`.
  - Use top-level `observedAt` for sun computation and response `computedAt`.
  - Validate location shape only in the backend: lat/lng ranges, timezone-aware `observedAt`, and non-negative optional `accuracyMeters`. Frontend owns freshness and accuracy gating for v1.
  - Preview anchors at the first coordinate of the first ordered route segment.
  - If onboard projection is off-route and `fallbackToPreview: true`, return preview advice from the direction start while preserving the requested `horizon`.
  - If onboard projection is off-route and fallback is false, return withheld with `reasonCode: "locationOffRoute"`.
  - `preview` requests ignore `fallbackToPreview`.
- Add explicit recommendation and condition semantics:
  - `recommendedSeatArea`: left->right, right->left, front->back, back->front, overhead/none->neutral.
  - Treat this v1 recommendation mapping as deterministic service behavior even though the frontend consumes `recommendedSeatArea` directly instead of deriving it.
  - `sunCondition`: `night` when elevation < 0, `lowSun` when 0 <= elevation < 10, `overhead` when elevation >= 70, otherwise `daylight`.
  - Produce one internally consistent `directSunExposure`, `recommendedSeatArea`, and `sunCondition` for the selected horizon. Classify `sunCondition` from the dominant distance-weighted exposure sample for that horizon.
  - If the selected horizon has no computable distance, return withheld with `reasonCode: "noAdviceForSelectedHorizon"`.
  - Night is successful neutral advice, not withheld.
- Standardize public errors:
  - Use `{ "error": { "code": "...", "message": "..." } }`.
  - Omit `requestId` for now.
  - Validation failures return `422 validationFailed`, including malformed UUIDs, missing required fields, invalid enum values, invalid query values, and invalid request bodies.
  - Replace FastAPI/Pydantic's default public `detail` response shape with the standard error envelope.
  - Return `404 routeNotFound` when no current route exists for the supplied `routeId`.
  - Return `409 routeVersionStale` only when the supplied `routeId` exists as current route data but the supplied `routeVersionId` is not that route's current version.
  - Return `404 routeDirectionNotFound` when the route/version pair is current but the supplied `routeDirectionId` does not belong to that current version.
  - Valid route/version/direction rows with no materialized geometry return successful empty geometry from the geometry endpoint and `withheld` advice with `reasonCode: "missingRouteGeometry"` from the advice endpoint.
  - Use `serviceUnavailable` for unexpected service-side failures.
- Keep UUIDs as the actual backend ID format while treating IDs as opaque strings in the public contract.
- Service docs, README examples, and tests should use UUID-shaped IDs because the service validates incoming IDs as UUIDs; frontend code still treats those strings as opaque.
- Update CORS defaults to include `http://localhost:3000` and keep `http://localhost:5173`; deployed origins remain env-configured.

## Implementation Notes

- Implement API contract tests first. Start with new public paths, camelCase query/body/response fields, default values, standard error envelopes, and generated OpenAPI absence of the retired endpoints before refactoring internals.
- Use browser-facing Pydantic schemas that serialize camelCase. Query parameters should accept camelCase names such as `radiusMeters` and `routeVersionId`.
- Keep camelCase at the HTTP boundary only. FastAPI handlers translate public camelCase query/body fields into snake_case service calls; SQL params, service methods, database models, and internal read DTOs stay snake_case.
- Retire old public tests/docs for `/v1/routes`, `/v1/nearby-route-directions`, `/v1/route-directions/{id}/segments`, and `/v1/onboard-advisories` rather than preserving old response shapes.
- Remove the old public endpoints from the FastAPI runtime in this slice; generated OpenAPI should expose `/health/live` plus the new browser contract endpoints only.
- Keep SQLAlchemy ORM/Core read-query style per the existing ADR; do not introduce raw textual SQL.
- Add route/version/direction validation helpers so handlers can distinguish stale versions, missing routes, missing directions, and missing geometry.
- Update `CONTEXT.md` as glossary only, with no implementation details. Add an ADR documenting the frontend-owned browser API replacement and why old route-summary/advisory public contracts were retired.

## Test Plan

- API tests for all new endpoints and camelCase response/request fields.
- Route candidate tests proving nearby/search return route-only candidates, ordered departure-label hints, frontend defaults, and no direction IDs.
- Direction tests for current version success, `200 directions: []` when a current route has no usable direction choices, stale version `409`, route not found, and direction not found.
- Geometry tests for flattened `{lat,lng}` polyline conversion, adjacent duplicate removal, empty geometry success, and stale/not-found errors.
- Advice tests for onboard, preview, all horizons, fallback-to-preview, off-route withheld, missing geometry withheld, neutral night, low sun, overhead, and seat-area recommendation mapping.
- Error-envelope tests for validation, stale version, not found, and service unavailable paths.
- CORS/config tests confirming local Next and existing local origin defaults.

## Assumptions

- This backend repo is the implementation target; frontend docs are edited only to keep the shared API contract consistent when this plan settles a contract term or code.
- Existing health endpoints remain unchanged.
- No request-id middleware is added in this slice.
