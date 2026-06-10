# Frontend-Owned Browser API Contract

Sombreado Service will expose the frontend-owned browser contract as its v1 public API, using route candidates, direction choices, route geometry, and advice as the public language. We are retiring the older route-summary, nearby-route-direction, segment, and onboard-advisory public shapes instead of maintaining dual contracts, because the browser flow needs route selection before direction selection and should not adapt backend-owned response shapes at the product boundary.
