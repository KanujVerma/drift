import { homedir } from "node:os";
import { join } from "node:path";
import { ChatGPTAuth, ChatGPTAuthError } from "./chatgpt-auth.js";

const credentialPath = join(homedir(), ".local", "share", "drift", "chatgpt-signin", "auth.json");
const auth = new ChatGPTAuth({ path: credentialPath });

if (process.argv.length !== 3 || !["signin", "status", "refresh"].includes(process.argv[2] ?? "")) {
  process.stderr.write("Usage: node dist/cli.js signin|status|refresh\n");
  process.exitCode = 2;
} else {
  try {
    if (process.argv[2] === "signin") {
      const account = await auth.signIn({ say: (line) => process.stdout.write(`${line}\n`) });
      process.stdout.write(`Drift authorization completed for ${account}.\n`);
    } else if (process.argv[2] === "refresh") {
      await auth.accessToken();
      process.stdout.write("Drift authorization is current.\n");
    } else {
      const identity = await auth.identity();
      if (!identity) throw new ChatGPTAuthError("Drift is not authorized to use a plan.");
      process.stdout.write(`Account: ${identity.email ?? "email unavailable"}\nSubject: ${identity.subject}\n`);
    }
  } catch (error) {
    // Never print raw HTTP bodies, callback URLs, OAuth codes, or credentials.
    process.stderr.write(`Drift authorization failed: ${error instanceof ChatGPTAuthError ? error.message : "unknown error"}\n`);
    process.exitCode = 1;
  }
}
