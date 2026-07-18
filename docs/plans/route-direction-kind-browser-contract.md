# Route Direction Kind Browser Contract

## Summary

Expose the scraper-owned Route Direction Kind through the existing Direction Choices endpoint so Sombreado Floripa can show a stable `Ida` or `Volta` cue during direction selection without parsing raw KML names.

This extends the existing browser contract; it does not add an endpoint or change Direction Choice eligibility, ordering, labels, or geometry behavior.

## Public Contract

```http
GET /v1/routes/{routeId}/directions?routeVersionId={routeVersionId}
```

Each Direction Choice adds one required-but-nullable camelCase field:

```ts
type DirectionChoice = {
  routeDirectionId: string;
  sequence: number;
  name: string;
  directionKind: "ida" | "volta" | null;
  departureLabels: string[];
};
```

Example:

```json
{
  "directions": [
    {
      "routeDirectionId": "00000000-0000-0000-0000-000000000001",
      "sequence": 1,
      "name": "294 Ida T.SAN - T.FOR",
      "directionKind": "ida",
      "departureLabels": ["T.SAN"]
    }
  ]
}
```

## Semantics

- Map `directionKind` directly from the current scraper-owned `route_directions.direction_kind` column.
- Return exactly `"ida"`, `"volta"`, or `null`; never omit the field.
- Do not rescan `name`, infer a complementary kind, or derive the kind from Departure Labels.
- Null is valid Current Route Data. It includes singleton, ambiguous, and unlabeled directions, plus unchanged Route Versions created before classification existed.
- Null does not remove, disable, or reorder a Direction Choice.
- Preserve `routeDirectionId`, `sequence`, `name`, and `departureLabels` unchanged.

## Backend Slice

- Map the nullable `direction_kind` column on `RouteDirectionRecord`.
- Add `direction_kind: Literal["ida", "volta"] | None` to the internal/public Direction Choice data path.
- Select `RouteDirectionRecord.direction_kind` in the Direction Choice query.
- Let the existing browser schema aliasing serialize it as `directionKind`.
- Update API, query-mapping, and generated OpenAPI tests.
- Keep Sombreado Service read-only; the scraper remains responsible for classification and migration.

## Rollout

Deploy the backend contract before deploying a frontend validator that requires `directionKind`. Existing frontend schemas tolerate the additional field, while the new frontend schema should reject a response that omits it.

## Verification

- A classified current pair returns one `ida` and one `volta` value.
- A valid unclassified direction returns `directionKind: null` and remains selectable.
- Direction ordering, raw names, Departure Labels, stale-version errors, and empty-direction behavior remain unchanged.
