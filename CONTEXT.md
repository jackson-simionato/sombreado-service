# Sombreado Service

This context describes the backend that serves onboard sun-side guidance. Today the passenger API still reads scraper-owned route data; the codebase is reshaping toward dual entry points (API + scrape CLI) that will later own ingestion.

## Language

**Sombreado Service**:
The installable backend package with two process entry points: the passenger-facing browser API and the scrape CLI. Until cutover, the API still computes Advice from scraper-owned **Current Route Data**.
_Avoid_: Naming the whole product only as “the scraper”; calling the passenger API an “ingestion service”

**Scrape CLI**:
The separate OS-process entry point that fetches Consórcio Fênix data, validates a staged **Dataset Generation**, and publishes into the **Generation Store** under the production operating policy (lease, absence-vs-hard-failure, one retry). It can also publish fixture generations for demos.
_Avoid_: In-process scrape inside API requests, scraper repository runtime

**Generation Store**:
The service-owned SQLite WAL datastore with generation-keyed route rows, R*Tree coarse nearby filtering, and revised application geodesic exact distance. Not yet the passenger API read path.
_Avoid_: Scraper Database, app database, SpatiaLite

**Dataset Generation**:
One complete scrape/fixture snapshot in the **Generation Store**, addressed by generation id. Roles are staging (in-flight), current (passenger-visible pointer), and previous (immediate prior current).
_Avoid_: Route version history archive, active dataset file swap

**Scrape Lease**:
The singleton DB-backed mutual-exclusion record that prevents overlapping scrape/fixture publish jobs against the **Generation Store**.
_Avoid_: Distributed lock service, API request lock

**Scraper Database**:
The PostGIS database owned by the Consorcio Fenix scraper and consumed read-only by the Sombreado Service API until centralized SQLite cutover.
_Avoid_: App database, service database, Generation Store

**Reader Database Role**:
The separate database user used by the Sombreado Service API with SELECT-only access to scraper-owned tables (current passenger-read path).
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
The passenger-facing API surface for finding current route candidates, selecting a direction, and loading route geometry before requesting advice.
_Avoid_: Route administration, scraper inspection

**Route Search**:
Text filtering over current route codes and names for route catalogue browsing.
_Avoid_: Nearby direction lookup, full-text indexing

**Route Candidate Limit**:
The maximum number of route candidates returned by a route discovery request, with separate defaults for nearby discovery and route search.
_Avoid_: Offset pagination, cursor pagination

**Nearby Route Filter**:
Geospatial filtering that finds current routes near a passenger location.
_Avoid_: Advisory projection, selected direction

**Route Candidate**:
A current route option shown before a passenger chooses a direction, with route identity, current version identity, optional distance, and zero or more direction hints.
_Avoid_: Route summary, route detail, selectable direction

**Direction Hint**:
A non-selectable departure label shown on a route candidate to help a passenger recognize boarding or destination context before choosing a direction.
_Avoid_: Direction choice, direction identifier, route direction name

**Direction Choice**:
A selectable current route direction for a selected route candidate. Its usability comes from current route-direction data, not from departure-label or geometry availability.
_Avoid_: Segment geometry, service timetable

**Route Direction Kind**:
An optional semantic classification of a Direction Choice as `ida` or `volta`, supplied by the scraper only for an unambiguous route-direction pair.
_Avoid_: Parsed direction name, inferred complementary direction, departure label

**Departure Label**:
A passenger-facing label from scraper service direction data that helps distinguish how a route direction is boarded, announced, or recognized.
_Avoid_: Public service direction resource, timetable

**Direction Match Confidence**:
The scraper's confidence that a service direction belongs to a route direction.
_Avoid_: Rider-facing route quality, schedule confidence

**Route Geometry**:
The passenger-facing ordered polyline for one current direction choice.
_Avoid_: Route candidate, stop list

**Advice**:
A passenger-facing sun-side result for a selected current direction.
_Avoid_: Preview Advice, Onboard advisory, route discovery result

**Advice Mode**:
The passenger context used to compute Advice, either onboard from a passenger location or preview from the selected route direction.
_Avoid_: Preview Advice, onboard advisory type, advice endpoint variant

**Advice Horizon**:
The route window used to compute advice, either the upcoming portion near the passenger or the remaining route.
_Avoid_: Include remaining flag, response section

**Advice Position**:
The passenger-facing point on the selected direction where Advice is anchored. For onboard Advice it is derived from the passenger's live location; for preview Advice it is the selected direction start.
_Avoid_: Raw browser location, stop location, route geometry

**Sun Condition**:
A coarse daylight context attached to advice, such as night, low sun, daylight, or overhead sun.
_Avoid_: Raw solar elevation, azimuth debug value

**Seat-area Recommendation**:
The passenger-facing seating area suggested by Advice to reduce direct sun exposure, such as left, right, front, back, or neutral.
_Avoid_: Seat-side recommendation, frontend-derived recommendation, raw exposure inversion

## Relationships

- The **Sombreado Service** exposes separate API and **Scrape CLI** processes that share package code, not process lifecycle.
- Until cutover, the API consumes the **Scraper Database** through the **Reader Database Role**.
- The **Scrape CLI** owns live Consórcio fetch, migrate, and publish against the **Generation Store**; passenger API reads do not use it yet.
- A **Dataset Generation** becomes passenger-visible only through the current pointer after validate-then-publish.
- Incomplete staging never auto-publishes; failure retains the last successful current (+ previous when present).
- A **Reader Database Role** must not mutate scraper-owned route data.
- The **Scrape CLI** must not run inside the API request path.
- **Route Discovery** exposes only **Current Route Data**.
- **Route Discovery** supports **Route Search** and a **Nearby Route Filter**.
- **Route Search** returns **Route Candidates** by route code and route name.
- A **Nearby Route Filter** sorts **Route Candidates** by passenger relevance.
- A **Route Candidate Limit** bounds route discovery responses without offset or cursor pagination.
- Nearby discovery and route search use different **Route Candidate Limit** defaults.
- A **Route Candidate** may include zero or more **Direction Hints**.
- A **Route Candidate** does not include selectable direction identifiers.
- A **Route Search** may return a **Route Candidate** with no **Direction Hints**.
- A **Nearby Route Filter** returns only **Route Candidates** close enough to the passenger to have meaningful distance.
- **Direction Choices** are discovered after a passenger selects a **Route Candidate**.
- A **Direction Choice** may have a **Route Direction Kind**.
- A missing **Route Direction Kind** does not make a **Direction Choice** unusable.
- A **Direction Choice** may have zero, one, or many **Departure Labels**.
- Public **Departure Labels** use high or medium **Direction Match Confidence**.
- **Departure Labels** do not determine whether a **Direction Choice** is usable.
- **Route Geometry** does not determine whether a **Direction Choice** is usable.
- **Route Geometry** belongs to exactly one current **Direction Choice**.
- A **Route Candidate** does not include **Route Geometry**.
- **Advice** is requested after a passenger selects a **Direction Choice**.
- An **Advice Mode** distinguishes onboard passenger context from route preview context for **Advice**.
- An **Advice Horizon** selects one computation window for an **Advice** result.
- An onboard **Advice Horizon** starts at the onboard **Advice Position**.
- A preview **Advice Horizon** starts at the selected direction start.
- **Advice** may include an **Advice Position** to show the anchor used for computation.
- Onboard **Advice Position** is derived from live passenger location rather than exposing the raw browser fix.
- Preview **Advice Position** uses the selected direction start.
- A **Sun Condition** describes the selected **Advice Horizon**, not individual route segments.
- A **Seat-area Recommendation** is produced by **Advice** and is not derived by the browser client.
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
> **Domain expert:** "No — a **Nearby Route Filter** narrows the route catalogue to **Route Candidates**, while **Direction Choices** are loaded after route selection."
>
> **Dev:** "Should a route listing force the app to call another endpoint before a passenger can choose a direction?"
> **Domain expert:** "Yes — a **Route Candidate** is route-only, and **Direction Choices** are selected through the next route discovery step."
>
> **Dev:** "Should **Route Search** return all coordinates for every matching route?"
> **Domain expert:** "No — clients request **Route Geometry** only after choosing a current route direction."
>
> **Dev:** "Should clients browse service directions directly?"
> **Domain expert:** "No — **Departure Labels** appear as **Direction Hints** on route candidates and as labels on **Direction Choices**; service directions are scraper-owned supporting data."
>
> **Dev:** "Should opening a saved route load geometry immediately?"
> **Domain expert:** "No — clients should restore through current **Route Candidates** and **Direction Choices**; **Route Geometry** is requested separately."
>
> **Dev:** "Do route listings need offset pagination?"
> **Domain expert:** "No — use a **Route Candidate Limit**; current route discovery is small enough to avoid cursor or offset pagination for now."
>
> **Dev:** "Should the API expose a standalone direction detail endpoint?"
> **Domain expert:** "No — passengers discover **Direction Choices** through a selected route, then use the direction ID for **Advice** or **Route Geometry**."
>
> **Dev:** "If a nearby route direction has multiple service labels, should we pick one?"
> **Domain expert:** "No — use **Departure Labels** as **Direction Hints** for route recognition, then return **Departure Labels** again on selectable **Direction Choices**."

## Flagged ambiguities

- The **Generation Store** exists for fixture publish and upcoming scrape ownership, but passenger reads still use the **Reader Database Role** / **Scraper Database** until SQLite cutover.
- "database user" means the **Reader Database Role** for this service's API, not the scraper's ingestion or migration role.
- "deploy" means GitHub Actions triggering the **Render Deployment** after CI passes on `main`, not Render auto-deploying before CI.
- `DATABASE_URL` is a **Runtime Secret**, not a **Pipeline Secret**.
- "route listing" means listing **Current Route Data**, not exposing historical or archived route versions.
- "filtering" means **Route Search** and optional **Nearby Route Filter**, not scraper administration queries.
- "pagination" means **Route Candidate Limit** only, not offset or cursor pagination.
- "directions inline" means **Direction Hints**, not selectable directions, route segment geometry, or timetables.
- "direction detail" means **Direction Choices** under a route, not a standalone route-direction resource.
- "geometry" means **Route Geometry** for one current direction choice, not an inline field on every **Route Candidate**.
- "service directions" means **Departure Labels** attached to directions, not a standalone public resource.
- "route detail" is retired public language; use **Route Candidate** before direction selection and **Direction Choice** after route selection.
- "horizon" means the selected **Advice Horizon**, not a request to return multiple windows in one advice response.
