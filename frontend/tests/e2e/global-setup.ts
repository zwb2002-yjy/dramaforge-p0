import path from "node:path";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export default async function globalSetup() {
  const port = Number.parseInt(process.env.DRAMAFORGE_E2E_PORT ?? "4173", 10);
  // E2E runs an in-process Vite gateway while the Compose API is reachable
  // through the published frontend gateway on port 8080.
  process.env.DRAMAFORGE_API_URL ??=
    process.env.DRAMAFORGE_E2E_API_URL ?? "http://127.0.0.1:8080";
  const server = await createServer({
    root: frontendRoot,
    configFile: path.join(frontendRoot, "vite.config.ts"),
    server: {
      host: "127.0.0.1",
      port,
      strictPort: true,
    },
  });

  await server.listen();

  return async () => {
    await server.close();
  };
}
