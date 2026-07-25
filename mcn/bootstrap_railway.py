#!/usr/bin/env python3
"""Bootstrap the ACX City Railway project from nothing — no dashboard clicks.

Creates (idempotently) in the Railway project `acx-city`:
    backend   — GitHub repo service (root backend/,  backend/railway.toml)
    worker    — GitHub repo service (root backend/,  backend/railway.worker.toml)
    frontend  — GitHub repo service (root frontend/, frontend/railway.toml)
    postgres  — ghcr.io/railwayapp-templates/postgres-ssl:16 + volume
    minio     — bitnami/minio + volume (shared object storage for audio)

Railway volumes attach to exactly ONE service (platform limitation), so the
backend and worker do NOT share a filesystem. Instead each gets a private
/data scratch volume and both use the S3 storage backend against MinIO —
`backend/storage/s3.py` already supports this natively.

Usage:
    python3 bootstrap_railway.py --dry-run   # show the plan, no API calls
    python3 bootstrap_railway.py             # create everything

Auth: RAILWAY_TOKEN from mcn/.env.local or the process environment
(railway.com → Account Settings → Tokens). After this succeeds, run
`python3 provision.py` to push app-level env vars, deploy, then rerun
provision.py once so live URLs resolve.
"""
import argparse
import sys

from provision import gql, load_env_local, load_or_create_secrets

PROJECT = "acx-city"
REPO = "redinc23/acx-city"
BRANCH = "main"
BUCKET = "audiobook-data"

BOOTSTRAP_SECRETS = {
    "POSTGRES_PASSWORD": {"bytes": 16},
    "MINIO_ROOT_USER": {"bytes": 8},
    "MINIO_ROOT_PASSWORD": {"bytes": 16},
}

# ${{service.VAR}} strings are Railway reference variables, resolved by the
# platform at deploy time — they never pass through this script as plaintext.
STORAGE_WIRING = {
    "DATABASE_URL": "${{postgres.DATABASE_URL}}",
    "POSTGRES_PASSWORD": "${{postgres.POSTGRES_PASSWORD}}",
    "STORAGE_BACKEND": "s3",
    "STORAGE_S3_BUCKET": BUCKET,
    "STORAGE_S3_REGION": "us-east-1",
    "STORAGE_S3_ENDPOINT": "https://${{minio.RAILWAY_PUBLIC_DOMAIN}}",
    "STORAGE_S3_ACCESS_KEY": "${{minio.MINIO_ROOT_USER}}",
    "STORAGE_S3_SECRET_KEY": "${{minio.MINIO_ROOT_PASSWORD}}",
}


def service_plan(secrets):
    return {
        "backend": {
            "source": {"repo": REPO}, "branch": BRANCH,
            "instance": {"rootDirectory": "backend",
                         "railwayConfigFile": "backend/railway.toml"},
            "volume": "/data", "domain_port": 5000,
            "vars": dict(STORAGE_WIRING),
        },
        "worker": {
            "source": {"repo": REPO}, "branch": BRANCH,
            "instance": {"rootDirectory": "backend",
                         "railwayConfigFile": "backend/railway.worker.toml"},
            "volume": "/data",
            "vars": dict(STORAGE_WIRING),
        },
        "frontend": {
            "source": {"repo": REPO}, "branch": BRANCH,
            "instance": {"rootDirectory": "frontend",
                         "railwayConfigFile": "frontend/railway.toml"},
            "domain_port": None,
            "vars": {"BACKEND_PRIVATE_URL":
                     "http://${{backend.RAILWAY_PRIVATE_DOMAIN}}:5000"},
        },
        "postgres": {
            "source": {"image": "ghcr.io/railwayapp-templates/postgres-ssl:16"},
            "volume": "/var/lib/postgresql/data",
            "vars": {
                "POSTGRES_USER": "postgres",
                "POSTGRES_DB": "railway",
                "POSTGRES_PASSWORD": secrets["POSTGRES_PASSWORD"],
                "PGDATA": "/var/lib/postgresql/data/pgdata",
                "SSL_CERT_DAYS": "820",
                "DATABASE_URL": ("postgresql://${{POSTGRES_USER}}:${{POSTGRES_PASSWORD}}"
                                 "@${{RAILWAY_PRIVATE_DOMAIN}}:5432/${{POSTGRES_DB}}"),
            },
        },
        "minio": {
            "source": {"image": "bitnami/minio:latest"},
            "volume": "/bitnami/minio/data", "domain_port": 9000,
            "vars": {
                "MINIO_ROOT_USER": secrets["MINIO_ROOT_USER"],
                "MINIO_ROOT_PASSWORD": secrets["MINIO_ROOT_PASSWORD"],
                "MINIO_DEFAULT_BUCKETS": BUCKET,
                # Railway volumes are root-owned; bitnami images run non-root.
                "RAILWAY_RUN_UID": "0",
            },
        },
    }


class Bootstrap:
    def __init__(self, token):
        self.token = token
        self.refresh()

    def refresh(self):
        data = gql(self.token, """
          query { projects { edges { node {
            id name
            environments { edges { node { id name } } }
            services { edges { node { id name
              serviceInstances { edges { node { environmentId
                domains { serviceDomains { domain } } } } } } } }
            volumes { edges { node { id name
              volumeInstances { edges { node { serviceId mountPath } } } } } }
          } } } }""")
        self.project = next((e["node"] for e in data["projects"]["edges"]
                             if e["node"]["name"] == PROJECT), None)

    def ensure_project(self):
        if self.project:
            print(f"project {PROJECT}: exists")
        else:
            gql(self.token, """
              mutation($input: ProjectCreateInput!) {
                projectCreate(input: $input) { id } }""",
                {"input": {"name": PROJECT}})
            print(f"project {PROJECT}: created")
            self.refresh()
        envs = [e["node"] for e in self.project["environments"]["edges"]]
        self.env_id = next((e["id"] for e in envs if e["name"] == "production"),
                           envs[0]["id"])
        self.services = {s["node"]["name"]: s["node"]
                         for s in self.project["services"]["edges"]}
        self.volumes = [v["node"] for v in self.project["volumes"]["edges"]]

    def ensure_service(self, name, cfg):
        svc = self.services.get(name)
        if svc:
            print(f"  service {name}: exists")
        else:
            inp = {"projectId": self.project["id"], "name": name,
                   "source": cfg["source"]}
            if cfg.get("branch"):
                inp["branch"] = cfg["branch"]
            try:
                svc = gql(self.token, """
                  mutation($input: ServiceCreateInput!) {
                    serviceCreate(input: $input) { id name } }""",
                    {"input": inp})["serviceCreate"]
            except RuntimeError as e:
                if "repo" in cfg["source"]:
                    print(f"  !! service {name}: {e}\n"
                          f"     If this mentions repo access, install the Railway"
                          f" GitHub App on {REPO}\n"
                          f"     (railway.com → Account Settings → GitHub) and rerun.")
                    return None
                raise
            print(f"  service {name}: created")
            self.services[name] = {"id": svc["id"], "name": name,
                                   "serviceInstances": {"edges": []}}
            svc = self.services[name]

        if cfg.get("instance"):
            gql(self.token, """
              mutation($serviceId: String!, $environmentId: String,
                       $input: ServiceInstanceUpdateInput!) {
                serviceInstanceUpdate(serviceId: $serviceId,
                  environmentId: $environmentId, input: $input) }""",
                {"serviceId": svc["id"], "environmentId": self.env_id,
                 "input": cfg["instance"]})
            print(f"    settings: {cfg['instance']}")

        if cfg.get("volume"):
            has = any(vi["node"]["serviceId"] == svc["id"]
                      for v in self.volumes
                      for vi in v["volumeInstances"]["edges"])
            if has:
                print("    volume: exists")
            else:
                gql(self.token, """
                  mutation($input: VolumeCreateInput!) {
                    volumeCreate(input: $input) { id } }""",
                    {"input": {"projectId": self.project["id"],
                               "environmentId": self.env_id,
                               "serviceId": svc["id"],
                               "mountPath": cfg["volume"]}})
                print(f"    volume: created at {cfg['volume']}")

        if cfg.get("vars"):
            gql(self.token, """
              mutation($input: VariableCollectionUpsertInput!) {
                variableCollectionUpsert(input: $input) }""",
                {"input": {"projectId": self.project["id"],
                           "environmentId": self.env_id,
                           "serviceId": svc["id"],
                           "variables": cfg["vars"]}})
            print(f"    vars: {len(cfg['vars'])} set")

        if "domain_port" in cfg:
            existing = [d["domain"]
                        for inst in svc["serviceInstances"]["edges"]
                        for d in inst["node"]["domains"]["serviceDomains"]]
            if existing:
                print(f"    domain: https://{existing[0]}")
            else:
                inp = {"environmentId": self.env_id, "serviceId": svc["id"]}
                if cfg["domain_port"]:
                    inp["targetPort"] = cfg["domain_port"]
                out = gql(self.token, """
                  mutation($input: ServiceDomainCreateInput!) {
                    serviceDomainCreate(input: $input) { domain } }""",
                    {"input": inp})
                print(f"    domain: https://{out['serviceDomainCreate']['domain']}")

        return svc

    def deploy(self, name):
        svc = self.services.get(name)
        if not svc:
            return
        try:
            gql(self.token, """
              mutation($serviceId: String!, $environmentId: String!) {
                serviceInstanceDeployV2(serviceId: $serviceId,
                                        environmentId: $environmentId) }""",
                {"serviceId": svc["id"], "environmentId": self.env_id})
            print(f"  deploy {name}: triggered")
        except RuntimeError as e:
            print(f"  deploy {name}: skipped ({e})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    secrets = load_or_create_secrets(BOOTSTRAP_SECRETS)
    plan = service_plan(secrets)

    if args.dry_run:
        print(f"Would ensure Railway project '{PROJECT}' with:")
        for name, cfg in plan.items():
            src = cfg["source"].get("repo") or cfg["source"].get("image")
            extras = []
            if cfg.get("volume"):
                extras.append(f"volume {cfg['volume']}")
            if "domain_port" in cfg:
                extras.append("public domain")
            print(f"  {name}: {src}"
                  + (f"  [{', '.join(extras)}]" if extras else ""))
            for k, v in (cfg.get("vars") or {}).items():
                shown = "<generated secret>" if v in secrets.values() else v
                print(f"    {k}={shown}")
        print("\nDry run only — nothing was sent.")
        return

    local = load_env_local()
    if "RAILWAY_TOKEN" not in local:
        sys.exit("Set RAILWAY_TOKEN in mcn/.env.local or the environment "
                 "(railway.com → Account Settings → Tokens), or use --dry-run.")

    bs = Bootstrap(local["RAILWAY_TOKEN"])
    bs.ensure_project()
    for name, cfg in plan.items():
        bs.ensure_service(name, cfg)
    for name in plan:
        bs.deploy(name)

    print("\nBootstrap done. Next: python3 provision.py  (then rerun once "
          "after first deploys so live URLs resolve).")


if __name__ == "__main__":
    main()
