# Overwrite Render Free cutover onto Neon

## Status

Accepted. Supersedes #29 / #43 for map #53. Implementation vehicle: epic #66 slice 6 / issue #73.

## Decision

### Traffic switch

Overwrite the existing **Render Free** web service in place with Neon-backed Sombreado Service. Frontend `NEXT_PUBLIC_API_URL` / DNS stay **unchanged**. No dual-Render warm PostGIS rollback host.

### Sequence

1. Prepare Neon + Actions scrape / Deploy Hook; reuse the existing Render Free service.
2. Bootstrap empty Neon schema → fresh full scrape → validate → publish `current` (new IDs; no history import).
3. Acceptance **before** overwrite against a Neon-backed build of the **same artifact** that will overwrite production (preview/pre-promote is enough):
   - validated `current`
   - browser-contract suite vs that Neon-backed artifact
   - Floripa smoke
   - **Not required:** offline backup gate; bit-identical nearby; UUID continuity
4. Overwrite-deploy the Neon-backed release to the existing Render service.
5. At flip: **immediately stop** standalone Consórcio Fênix scraper writes; no dual writers after passengers are on Neon.
6. Hold old scraper PostGIS **~48h** idle for emergency redeploy of pre-cutover code only.
7. Destroy PostGIS with **no** archive dump; update CONTEXT/ADRs; retire `consorcio-fenix-scraper` when retire-when holds.

### Rollback

| Window | Path |
| --- | --- |
| Before PostGIS destroy | Redeploy previous Render release against intact scraper PostGIS |
| After PostGIS destroy | Neon current/previous → ~6h PITR → fresh scrape (ADR 0007 / ADR 0008) |

### Scraper retire-when

Retire `consorcio-fenix-scraper` only when all hold:

- Neon-backed `main` serving Render Free from Neon `current`
- ≥1 successful Actions scrape publish after cutover
- Frontend still on that Render URL (`NEXT_PUBLIC_API_URL` unchanged)
- Scraper writes stopped and PostGIS destroyed
- Docs/ADRs updated
- No further scraper-repo commits expected

## Consequences

- Production passenger reads and scrape publish both target Neon; the standalone scraper PostGIS is not a passenger-read or dual-write path after flip.
- Cutover does not change the browser API contract (ADR 0003).
- Operators record remaining human steps (stop scraper writes, ~48h hold, destroy PostGIS, archive scraper repo) outside the agent-mergeable code path when credentials or console access require a human.
