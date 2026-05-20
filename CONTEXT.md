# Sombreado Service

This context describes the read-only advisory backend that serves onboard sun-side guidance from scraper-owned route data.

## Language

**Sombreado Service**:
The passenger-facing backend API that computes onboard sun-side advisories from current route segment data.
_Avoid_: Scraper, ingestion service

**Scraper Database**:
The PostGIS database owned by the Consorcio Fenix scraper and consumed read-only by the Sombreado Service.
_Avoid_: App database, service database

**Reader Database Role**:
The separate database user used by the Sombreado Service with SELECT-only access to scraper-owned tables.
_Avoid_: Migration user, scraper user, owner role

**Render Deployment**:
The no-cost web service runtime for the Sombreado Service, triggered by GitHub Actions after CI passes on `main`.
_Avoid_: VPS deployment, registry deployment, Render auto-deploy

**Pipeline Secret**:
A secret used by GitHub Actions to trigger or authenticate deployment automation.
_Avoid_: Runtime secret, application setting

**Runtime Secret**:
A secret consumed by the running Sombreado Service inside Render.
_Avoid_: Pipeline secret, CI variable

**Current Route Data**:
Passenger-usable route data from the scraper's current route and route version records.
_Avoid_: Historical route data, archived route versions

**Route Discovery**:
The passenger-facing API surface for finding current routes, directions, and route geometry before requesting an advisory.
_Avoid_: Route administration, scraper inspection

**Route Search**:
Text filtering over current route codes and names for route catalogue browsing.
_Avoid_: Nearby direction lookup, full-text indexing

**Route Listing Limit**:
The maximum number of current route summaries or nearby direction candidates returned by a route discovery request, defaulting to 10.
_Avoid_: Offset pagination, cursor pagination

**Nearby Route Filter**:
Geospatial filtering that finds current routes near a passenger location.
_Avoid_: Advisory projection, selected direction

**Route Summary**:
A current route listing item with route identity, its current version identifier, lightweight directions, and optional distance from a passenger location.
_Avoid_: Full route geometry, historical route version

**Route Detail**:
A stable lookup of one current route using the same passenger-facing data as a route summary.
_Avoid_: Geometry endpoint, historical route lookup

**Lightweight Direction**:
A selectable current route direction described by its identifier, sequence, scraper name, and passenger-facing departure labels.
_Avoid_: Segment geometry, service timetable

**Departure Label**:
A passenger-facing label from scraper service direction data that helps distinguish how a route direction is boarded or announced.
_Avoid_: Public service direction resource, timetable

**Route Geometry**:
The ordered segment coordinates and distance metadata for one current route direction.
_Avoid_: Route summary, stop list

## Relationships

- The **Sombreado Service** consumes the **Scraper Database** through the **Reader Database Role**.
- A **Reader Database Role** must not mutate scraper-owned route data.
- **Route Discovery** exposes only **Current Route Data**.
- **Route Discovery** supports **Route Search** and a **Nearby Route Filter**.
- **Route Search** sorts route summaries by route code and then route name.
- A **Nearby Route Filter** sorts route summaries by distance and then route code.
- A **Route Listing Limit** bounds route discovery responses without offset or cursor pagination.
- A **Route Listing Limit** defaults to 10 when the client does not request a limit.
- A **Route Summary** includes one or more **Lightweight Directions**.
- A **Route Detail** has the same passenger-facing fields as a **Route Summary**.
- **Lightweight Directions** are discovered through their route, not through a standalone direction detail resource.
- A **Lightweight Direction** may have zero, one, or many **Departure Labels**.
- Nearby route direction candidates return all **Departure Labels** for the direction.
- **Route Geometry** belongs to exactly one current route direction.
- A **Route Summary** does not include **Route Geometry**.
- A **Nearby Route Filter** finds routes, while nearby route direction lookup finds selectable directions for advisories.
- A **Render Deployment** runs the **Sombreado Service** and is triggered by GitHub Actions after CI passes on `main`.
- A **Pipeline Secret** belongs in GitHub Actions when CI/CD needs it.
- A **Runtime Secret** belongs in Render when the running service needs it.

## Example dialogue

> **Dev:** "Should the **Sombreado Service** run scraper migrations before deployment?"
> **Domain expert:** "No — the **Scraper Database** is owned by the scraper; the service only connects through the **Reader Database Role**."
>
> **Dev:** "Should **Route Discovery** let clients browse old route versions?"
> **Domain expert:** "No — passengers only need **Current Route Data**; version IDs may appear only so advisory requests can refer to the selected current route direction."
>
> **Dev:** "Is a nearby route filter the same as choosing a route direction for an advisory?"
> **Domain expert:** "No — a **Nearby Route Filter** narrows the route catalogue, while nearby route direction lookup returns selectable directions."
>
> **Dev:** "Should a route listing force the app to call another endpoint before a passenger can choose a direction?"
> **Domain expert:** "No — a **Route Summary** includes **Lightweight Directions** so the route can be selected directly."
>
> **Dev:** "Should **Route Search** return all coordinates for every matching route?"
> **Domain expert:** "No — clients request **Route Geometry** only after choosing a current route direction."
>
> **Dev:** "Should clients browse service directions directly?"
> **Domain expert:** "No — **Departure Labels** appear on **Lightweight Directions**; service directions are scraper-owned supporting data."
>
> **Dev:** "Should opening a saved route load geometry immediately?"
> **Domain expert:** "No — **Route Detail** restores the selected current route and directions; **Route Geometry** is requested separately."
>
> **Dev:** "Do route listings need offset pagination?"
> **Domain expert:** "No — use a **Route Listing Limit**; current route discovery is small enough to avoid cursor or offset pagination for now."
>
> **Dev:** "Should the API expose a standalone direction detail endpoint?"
> **Domain expert:** "No — passengers discover **Lightweight Directions** through routes, then use the direction ID for advisories or **Route Geometry**."
>
> **Dev:** "If a nearby route direction has multiple service labels, should we pick one?"
> **Domain expert:** "No — return all **Departure Labels** and use the default **Route Listing Limit** of 10 when no limit is provided."

## Flagged ambiguities

- "database user" means the **Reader Database Role** for this service, not the scraper's ingestion or migration role.
- "deploy" means GitHub Actions triggering the **Render Deployment** after CI passes on `main`, not Render auto-deploying before CI.
- `DATABASE_URL` is a **Runtime Secret**, not a **Pipeline Secret**.
- "route listing" means listing **Current Route Data**, not exposing historical or archived route versions.
- "filtering" means **Route Search** and optional **Nearby Route Filter**, not scraper administration queries.
- "pagination" means **Route Listing Limit** only, defaulting to 10, not offset or cursor pagination.
- "directions inline" means **Lightweight Directions**, not route segment geometry or timetables.
- "direction detail" means **Lightweight Directions** under a route, not a standalone route-direction resource.
- "geometry" means **Route Geometry** for one current route direction, not an inline field on every **Route Summary**.
- "service directions" means **Departure Labels** attached to directions, not a standalone public resource.
- "route detail" means a current **Route Detail**, not archived versions or full geometry.
