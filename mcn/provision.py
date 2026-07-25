#!/usr/bin/env python3
"""MCN provisioner — push every service's env vars to Railway + Vercel.

Usage:
    python provision.py --dry-run     # show the plan, no API calls
    python provision.py               # provision everything

One-time setup (mcn/.env.local, gitignored):
    RAILWAY_TOKEN=...     # railway.app → Account Settings → Tokens
    VERCEL_TOKEN=...      # vercel.com → Settings → Tokens
    VERCEL_TEAM_ID=...    # optional, only for team accounts

The same three variables are also read from the process environment
(e.g. CI secrets or Cursor Cloud Agent secrets); .env.local overrides.

Secrets in registry.yaml are generated on first run and persisted to
mcn/.secrets.json (gitignored) so reruns are idempotent.
"""
import argparse
import json
import os
import re
import secrets as pysecrets
import sys
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).parent
RAILWAY_GQL = "https://backboard.railway.com/graphql/v2"
VERCEL_API = "https://api.vercel.com"


def load_env_local():
    # Process environment (e.g. CI or Cursor Cloud Agent secrets) works as a
    # fallback; mcn/.env.local wins when both define the same key.
    env = {k: os.environ[k] for k in ("RAILWAY_TOKEN", "VERCEL_TOKEN", "VERCEL_TEAM_ID")
           if os.environ.get(k)}
    p = HERE / ".env.local"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def load_or_create_secrets(spec):
    p = HERE / ".secrets.json"
    store = json.loads(p.read_text()) if p.exists() else {}
    changed = False
    for name, cfg in (spec or {}).items():
        if name not in store:
            store[name] = pysecrets.token_hex((cfg or {}).get("bytes", 32))
            changed = True
    if changed:
        p.write_text(json.dumps(store, indent=2))
        p.chmod(0o600)
    return store


def http(url, token, method="GET", body=None, team=None):
    if team:
        url += ("&" if "?" in url else "?") + f"teamId={team}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        req.add_header("Content-Type", "application/json")
        data = json.dumps(body).encode()
    with urllib.request.urlopen(req, data) as r:
        return json.loads(r.read() or "{}")


def gql(token, query, variables=None):
    out = http(RAILWAY_GQL, token, "POST", {"query": query, "variables": variables or {}})
    if out.get("errors"):
        raise RuntimeError(f"Railway API: {out['errors']}")
    return out["data"]


class Railway:
    def __init__(self, token, project_name):
        self.token = token
        data = gql(token, """
          query { projects { edges { node {
            id name
            environments { edges { node { id name } } }
            services { edges { node { id name
              serviceInstances { edges { node { environmentId
                domains { serviceDomains { domain } } } } } } } }
          } } } }""")
        projects = [e["node"] for e in data["projects"]["edges"]]
        match = [p for p in projects if p["name"] == project_name]
        if not match:
            raise SystemExit(f"Railway project '{project_name}' not found. "
                             f"Have: {[p['name'] for p in projects]}")
        self.project = match[0]
        envs = [e["node"] for e in self.project["environments"]["edges"]]
        self.env_id = next((e["id"] for e in envs if e["name"] == "production"), envs[0]["id"])
        self.services = {s["node"]["name"]: s["node"]
                         for s in self.project["services"]["edges"]}

    def public_url(self, service_name):
        svc = self.services.get(service_name)
        if not svc:
            return None
        for inst in svc["serviceInstances"]["edges"]:
            doms = inst["node"]["domains"]["serviceDomains"]
            if doms:
                return "https://" + doms[0]["domain"]
        return None

    def set_vars(self, service_name, env_vars):
        svc = self.services.get(service_name)
        if not svc:
            print(f"  !! Railway service '{service_name}' not found — skipped "
                  f"(have: {list(self.services)})")
            return
        gql(self.token, """
          mutation($input: VariableCollectionUpsertInput!) {
            variableCollectionUpsert(input: $input) }""", {
            "input": {"projectId": self.project["id"],
                      "environmentId": self.env_id,
                      "serviceId": svc["id"],
                      "variables": env_vars}})
        print(f"  railway/{service_name}: {len(env_vars)} vars set")


class Vercel:
    def __init__(self, token, team=None):
        self.token, self.team = token, team

    def project(self, name):
        return http(f"{VERCEL_API}/v9/projects/{name}", self.token, team=self.team)

    def public_url(self, name):
        try:
            p = self.project(name)
        except Exception:
            return None
        targets = p.get("targets", {}).get("production", {})
        alias = targets.get("alias") or []
        return "https://" + (alias[0] if alias else f"{name}.vercel.app")

    def set_vars(self, name, env_vars):
        pid = self.project(name)["id"]
        body = [{"key": k, "value": v, "type": "encrypted",
                 "target": ["production", "preview"]} for k, v in env_vars.items()]
        http(f"{VERCEL_API}/v10/projects/{pid}/env?upsert=true",
             self.token, "POST", body, team=self.team)
        print(f"  vercel/{name}: {len(env_vars)} vars set")


def resolve(value, ctx):
    """Expand ${secret:...}, ${url:...}, ${local:...} in a registry value."""
    value = str(value)

    def sub(m):
        kind, arg = m.group(1), m.group(2)
        if kind == "secret":
            return ctx["secrets"][arg]
        if kind == "local":
            if arg not in ctx["local"]:
                ctx["warnings"].append(f"{arg} missing from .env.local")
                return f"<MISSING:{arg}>"
            return ctx["local"][arg]
        if kind == "url":
            platform, name = arg.split(":", 1)
            url = ctx["urls"].get((platform, name))
            if not url:
                ctx["warnings"].append(f"no public URL yet for {platform}:{name} "
                                       f"(deploy it once, then rerun)")
                return f"<PENDING:{platform}:{name}>"
            return url
        return m.group(0)

    return re.sub(r"\$\{(secret|local|url):([^}]+)\}", sub, value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    reg = yaml.safe_load((HERE / "registry.yaml").read_text())
    local = load_env_local()
    secret_store = load_or_create_secrets(reg.get("secrets"))
    ctx = {"secrets": secret_store, "local": local, "urls": {}, "warnings": []}

    railway_clients, vercel = {}, None
    if not args.dry_run:
        if "RAILWAY_TOKEN" not in local or "VERCEL_TOKEN" not in local:
            sys.exit("Set RAILWAY_TOKEN and VERCEL_TOKEN in mcn/.env.local "
                     "(see header of this file), or use --dry-run.")
        vercel = Vercel(local["VERCEL_TOKEN"], local.get("VERCEL_TEAM_ID"))
        for repo in reg["repos"].values():
            if "railway" in repo:
                pname = repo["railway"]["project"]
                railway_clients[pname] = Railway(local["RAILWAY_TOKEN"], pname)

    # Pass 1: discover public URLs so cross-references resolve.
    for repo in reg["repos"].values():
        for pname, client in railway_clients.items():
            for svc in repo.get("railway", {}).get("services", {}):
                url = client.public_url(svc)
                if url:
                    ctx["urls"][("railway", svc)] = url
        for key, proj in repo.get("vercel", {}).get("projects", {}).items():
            if vercel:
                url = vercel.public_url(proj["project"])
                if url:
                    ctx["urls"][("vercel", key)] = url

    # Pass 2: resolve and push.
    for repo_name, repo in reg["repos"].items():
        print(f"\n== {repo_name} ==")
        for svc, cfg in repo.get("railway", {}).get("services", {}).items():
            env_vars = {k: resolve(v, ctx) for k, v in (cfg.get("env") or {}).items()}
            if args.dry_run:
                print(f"  railway/{svc}:")
                for k, v in env_vars.items():
                    shown = "<generated secret>" if any(v == s for s in secret_store.values()) else v
                    print(f"    {k}={shown}")
            else:
                railway_clients[repo["railway"]["project"]].set_vars(svc, env_vars)
        for key, proj in repo.get("vercel", {}).get("projects", {}).items():
            env_vars = {k: resolve(v, ctx) for k, v in (proj.get("env") or {}).items()}
            if args.dry_run:
                print(f"  vercel/{proj['project']}:")
                for k, v in env_vars.items():
                    print(f"    {k}={v}")
            else:
                vercel.set_vars(proj["project"], env_vars)

    if ctx["warnings"]:
        print("\nWarnings:")
        for w in dict.fromkeys(ctx["warnings"]):
            print(f"  - {w}")
    print("\nDone." if not args.dry_run else "\nDry run only — nothing was sent.")


if __name__ == "__main__":
    main()
