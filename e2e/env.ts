import { config } from "dotenv";
import path from "node:path";

// Playwright runs each spec file in its own worker process — global-setup.ts
// loading the repo-root .env does not propagate to those. Any spec that
// needs a real credential (e.g. to exercise the login form directly, rather
// than relying on global-setup's already-saved storageState) imports this
// module first for its side effect.
config({ path: path.resolve(__dirname, "../.env") });
