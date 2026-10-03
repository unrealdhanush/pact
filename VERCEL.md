# Pact hackathon deployment

Import `unrealdhanush/pact` into Vercel from `main`. Leave Root Directory at the repository root. The checked-in configuration selects **Other**, builds with `node scripts/build-vercel.mjs`, and serves `dist`.

The frontend is hosted on Vercel. `/api/*` forwards to the existing FastAPI backend through a temporary Cloudflare connection. This preserves the negotiation, authority, fulfillment, and returns architecture. The public backend is running with sponsor credentials disabled, and the Connections panel identifies all local fallbacks. Checkout and logistics are simulations.

**Keep the presenting computer awake and its backend/tunnel processes running.** The temporary backend connection is not permanent hosting and has no uptime guarantee. When the tunnel address changes, update the rewrite destination in `vercel.json` and redeploy. For durable judging access, replace that destination with a permanently hosted FastAPI service; Pact currently keeps deal and intake state in process, so deploying it directly as stateless functions would require persistence changes.

After Vercel finishes deploying, use the production domain for the submission. Check in a signed-out browser that the landing page, workspace, approval, delivery tracking, and returns work.

Optional submission links on the production domain:

- `/assets/pact-keynote.html` — interactive zoom presentation
- `/assets/Pact-Keynote.pptx` — editable PowerPoint download
- `/assets/pact-film.mp4` — 28-second product film with music (an ad, not a full functional walkthrough)
- `/assets/PACT-thumbnail.png` — submission thumbnail

The build copies only the public `web` frontend and its assets. Secrets and local editor history are never part of `dist`.
