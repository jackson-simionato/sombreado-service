# Ida Before Volta Design

## Goal

Make the Direction Choices endpoint return `ida` choices before `volta` choices, followed by unclassified choices.

## Design

The route read service will apply a semantic sort after mapping database rows into `DirectionChoice` values. The sort key ranks `ida` first, `volta` second, and `None` last, then uses the scraper-owned `sequence` as the stable order within each group. This keeps the public response shape and direction eligibility unchanged while making the passenger-facing order independent of database row order.

The behavior applies to `GET /v1/routes/{routeId}/directions`. Route Candidate direction hints and geometry endpoints are outside this change because they do not list selectable Direction Choices.

## Verification

A service-level regression test will provide rows in mixed semantic order and assert the resulting order is `ida`, `volta`, then unclassified, with sequences ascending inside each group. Existing API and service tests plus the full repository checks will guard response serialization and unrelated behavior.
