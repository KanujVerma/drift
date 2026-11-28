import assert from "node:assert/strict";
import { createHash, createSign, generateKeyPairSync } from "node:crypto";
import { mkdtemp, readFile, rm, stat, chmod, writeFile, mkdir, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { ChatGPTAuth } from "../dist/chatgpt-auth.js";

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const key = { ...publicKey.export({ format: "jwk" }), kid: "fixture-key", alg: "RS256" };
const b64 = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
const jwt = (client, nonce, subject = "fixture-subject") => {
  const header = b64({ alg: "RS256", kid: "fixture-key" });
  const body = b64({ iss: "https://auth.openai.com", aud: client, sub: subject,
    exp: Math.floor(Date.now() / 1000) + 3600, nonce, email: "fixture@example.invalid" });
  const signer = createSign("RSA-SHA256");
  signer.update(`${header}.${body}`);
  return `${header}.${body}.${signer.sign(privateKey).toString("base64url")}`;
};

async function fixture(options = {}) {
  const dir = await mkdtemp(join(tmpdir(), "drift-signin-test-"));
  const path = join(dir, "auth", "auth.json");
  const requests = [];
  let authorization;
  const fetchMock = async (url, init = {}) => {
    requests.push({ url: String(url), init });
    if (String(url).endsWith("/.well-known/jwks.json")) return Response.json({ keys: [key] });
    if (String(url).endsWith("/oauth/token")) {
      const body = new URLSearchParams(init.body);
      assert.equal(body.get("client_id"), "oaiapp_fixture");
      if (body.get("grant_type") === "refresh_token") {
        assert.equal(body.get("refresh_token"), "fixture-refresh");
        return Response.json({ access_token: "fixture-rotated", refresh_token: "fixture-refresh-2",
          expires_in: 3600, id_token: jwt("oaiapp_fixture", undefined, options.refreshSubject) });
      }
      assert.equal(body.get("grant_type"), "authorization_code");
      assert.equal(body.get("code"), "fixture-code");
      assert.equal(body.get("redirect_uri"), authorization.searchParams.get("redirect_uri"));
      assert.equal(body.get("resource"), "https://api.openai.com/v1");
      assert.ok(body.get("code_verifier"));
      assert.equal(createHash("sha256").update(body.get("code_verifier")).digest("base64url"),
        authorization.searchParams.get("code_challenge"));
      if (options.beforeToken) await options.beforeToken(path);
      return Response.json({ access_token: "fixture-access", refresh_token: "fixture-refresh",
        expires_in: 3600, scope: options.denyScope ? "openid email" :
          "openid email profile offline_access resource.invoke chatgpt.tokens.use.direct",
        id_token: jwt("oaiapp_fixture", options.badNonce ? "wrong" : authorization.searchParams.get("nonce")) });
    }
    throw new Error("unexpected external request");
  };
  const auth = new ChatGPTAuth({ path, fetch: fetchMock });
  const say = (text) => {
    if (!text.startsWith("https://auth.openai.com/")) return;
    authorization = new URL(text);
    const callback = new URL(authorization.searchParams.get("redirect_uri"));
    callback.searchParams.set("state", options.badState ? "wrong" : authorization.searchParams.get("state"));
    callback.searchParams.set("code", "fixture-code");
    callback.searchParams.set("client_id", options.callbackClient ?? "oaiapp_fixture");
    setImmediate(() => { void fetch(callback).catch(() => {}); });
  };
  return { dir, path, auth, say, requests, get authorization() { return authorization; } };
}

test("registers Drift and validates an authorized account without exposing tokens", async () => {
  const f = await fixture();
  try {
    assert.equal(await f.auth.signIn({ say: f.say, port: 0, timeoutMs: 3000 }), "fixture@example.invalid");
    const query = f.authorization.searchParams;
    assert.equal(query.get("client_id"), "dynamic_agent_client");
    assert.equal(query.get("agent_name_hint"), "Drift");
    assert.match(query.get("ext_agent_host_id"), /^urn:uuid:/);
    assert.equal(query.get("code_challenge_method"), "S256");
    assert.ok(query.get("scope").includes("chatgpt.tokens.use.direct"));
    const saved = JSON.parse(await readFile(f.path, "utf8"));
    assert.equal(saved.account.subject, "fixture-subject");
    assert.equal(saved.account.client_id, "oaiapp_fixture");
    assert.equal(saved.tokens.access_token, "fixture-access");
    assert.ok(saved.tokens.id_token);
    assert.equal((await stat(f.path)).mode & 0o777, 0o600);
    assert.equal((await stat(join(f.dir, "auth"))).mode & 0o777, 0o700);
    assert.equal(f.requests.length, 2);
  } finally { await rm(f.dir, { recursive: true, force: true }); }
});

for (const conflict of ["account", "registration"]) {
  test(`a concurrent ${conflict} change cannot be overwritten`, async () => {
    const f = await fixture({ beforeToken: async (path) => {
      const current = JSON.parse(await readFile(path, "utf8"));
      if (conflict === "account") current.account = { client_id: "oaiapp_fixture", subject: "other-subject" };
      else current.registration = { client_id: "oaiapp_other" };
      await writeFile(path, JSON.stringify(current), { mode: 0o600 });
    }});
    try {
      await assert.rejects(f.auth.signIn({ say: f.say, port: 0, timeoutMs: 3000 }));
      const saved = JSON.parse(await readFile(f.path, "utf8"));
      if (conflict === "account") assert.equal(saved.account.subject, "other-subject");
      else assert.equal(saved.registration.client_id, "oaiapp_other");
      assert.equal(saved.tokens, undefined);
    } finally { await rm(f.dir, { recursive: true, force: true }); }
  });
}

test("concurrent first sign-ins cannot replace the winning account", async () => {
  const dir = await mkdtemp(join(tmpdir(), "drift-signin-race-"));
  const path = join(dir, "auth", "auth.json");
  let arrivals = 0;
  let release;
  const bothArrived = new Promise((resolve) => { release = resolve; });
  const start = (subject) => {
    let authorization;
    const fetchMock = async (url) => {
      if (String(url).endsWith("/.well-known/jwks.json")) return Response.json({ keys: [key] });
      if (String(url).endsWith("/oauth/token")) {
        arrivals += 1;
        if (arrivals === 2) release();
        await bothArrived;
        return Response.json({ access_token: `access-${subject}`, expires_in: 3600,
          scope: "openid resource.invoke chatgpt.tokens.use.direct",
          id_token: jwt("oaiapp_fixture", authorization.searchParams.get("nonce"), subject) });
      }
      throw new Error("unexpected external request");
    };
    const say = (text) => {
      if (!text.startsWith("https://auth.openai.com/")) return;
      authorization = new URL(text);
      const callback = new URL(authorization.searchParams.get("redirect_uri"));
      callback.searchParams.set("state", authorization.searchParams.get("state"));
      callback.searchParams.set("code", "fixture-code");
      callback.searchParams.set("client_id", "oaiapp_fixture");
      setImmediate(() => { void fetch(callback).catch(() => {}); });
    };
    return new ChatGPTAuth({ path, fetch: fetchMock }).signIn({ say, port: 0, timeoutMs: 3000 });
  };
  try {
    const outcomes = await Promise.allSettled([start("one"), start("two")]);
    assert.equal(outcomes.filter((outcome) => outcome.status === "fulfilled").length, 1);
    assert.equal(outcomes.filter((outcome) => outcome.status === "rejected").length, 1);
    const saved = JSON.parse(await readFile(path, "utf8"));
    assert.ok(["one", "two"].includes(saved.account.subject));
    assert.equal(saved.tokens.access_token, `access-${saved.account.subject}`);
  } finally { await rm(dir, { recursive: true, force: true }); }
});

for (const [name, subject] of [["same account", "fixture-subject"], ["different account", "wrong-subject"]]) {
  test(`token refresh with ${name}`, async () => {
    const f = await fixture({ refreshSubject: subject });
    try {
      await f.auth.signIn({ say: f.say, port: 0, timeoutMs: 3000 });
      const saved = JSON.parse(await readFile(f.path, "utf8"));
      saved.tokens.expires_at = Math.floor(Date.now() / 1000) - 1;
      await writeFile(f.path, JSON.stringify(saved), { mode: 0o600 });
      if (subject === "fixture-subject") {
        assert.equal(await f.auth.accessToken(), "fixture-rotated");
        const updated = JSON.parse(await readFile(f.path, "utf8"));
        assert.equal(updated.tokens.refresh_token, "fixture-refresh-2");
      } else {
        await assert.rejects(f.auth.accessToken());
        const updated = JSON.parse(await readFile(f.path, "utf8"));
        assert.equal(updated.tokens, undefined);
      }
    } finally { await rm(f.dir, { recursive: true, force: true }); }
  });
}

for (const [name, options] of [
  ["wrong nonce", { badNonce: true }],
  ["wrong state", { badState: true }],
  ["denied plan permission", { denyScope: true }],
]) {
  test(`refuses ${name}`, async () => {
    const f = await fixture(options);
    try {
      await assert.rejects(f.auth.signIn({ say: f.say, port: 0, timeoutMs: 250 }));
      assert.equal(await f.auth.canUsePlan(), false);
    } finally { await rm(f.dir, { recursive: true, force: true }); }
  });
}

test("rejects a changed issued client for a pending registration", async () => {
  const f = await fixture({ callbackClient: "different-client" });
  try {
    await mkdir(join(f.dir, "auth"), { mode: 0o700 });
    await writeFile(f.path, JSON.stringify({ host_id: "urn:uuid:fixture",
      registration: { client_id: "oaiapp_fixture" } }), { mode: 0o600 });
    await assert.rejects(f.auth.signIn({ say: f.say, port: 0, timeoutMs: 1000 }));
    assert.equal(f.requests.length, 0);
  } finally { await rm(f.dir, { recursive: true, force: true }); }
});

test("refuses credential files readable by other users", async () => {
  if (process.platform === "win32") return;
  const f = await fixture();
  try {
    await mkdir(join(f.dir, "auth"), { mode: 0o700 });
    await writeFile(f.path, "{}", { mode: 0o600 });
    await chmod(f.path, 0o644);
    await assert.rejects(f.auth.canUsePlan());
  } finally { await rm(f.dir, { recursive: true, force: true }); }
});

test("refuses a symlinked credential directory", async () => {
  if (process.platform === "win32") return;
  const f = await fixture();
  try {
    const target = join(f.dir, "other");
    await mkdir(target, { mode: 0o700 });
    await writeFile(join(target, "auth.json"), "{}", { mode: 0o600 });
    await symlink(target, join(f.dir, "auth"));
    await assert.rejects(f.auth.canUsePlan());
  } finally { await rm(f.dir, { recursive: true, force: true }); }
});

test("refuses corrupt credentials without registering a replacement", async () => {
  const f = await fixture();
  try {
    await mkdir(join(f.dir, "auth"), { mode: 0o700 });
    await writeFile(f.path, "{broken", { mode: 0o600 });
    await assert.rejects(f.auth.signIn({ say: f.say, port: 0, timeoutMs: 1000 }));
    assert.equal(await readFile(f.path, "utf8"), "{broken");
    assert.equal(f.requests.length, 0);
  } finally { await rm(f.dir, { recursive: true, force: true }); }
});
