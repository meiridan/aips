#!/usr/bin/env python3
"""Provision a Neon project + database via the Neon API.
Idempotent: reuses an existing 'maya-core' project if present.
Writes DATABASE_URL to .deploy.generated.env.
"""
import os
import sys
import truststore
truststore.inject_into_ssl()
import httpx

NEON_API = "https://console.neon.tech/api/v2"
PROJECT_NAME = "maya-core"
REGION = "aws-eu-central-1"


def headers():
    key = os.environ["NEON_API_KEY"]
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def get_org_id(client) -> str:
    resp = client.get(f"{NEON_API}/users/me/organizations", headers=headers())
    resp.raise_for_status()
    orgs = resp.json().get("organizations", [])
    if not orgs:
        raise RuntimeError("No Neon organizations found for this API key")
    return orgs[0]["id"]


def find_existing_project(client, org_id: str) -> str | None:
    resp = client.get(f"{NEON_API}/projects", headers=headers(), params={"org_id": org_id})
    resp.raise_for_status()
    for p in resp.json().get("projects", []):
        if p["name"] == PROJECT_NAME:
            return p["id"]
    return None


def create_project(client, org_id: str) -> str:
    payload = {
        "project": {
            "name": PROJECT_NAME,
            "region_id": REGION,
            "pg_version": 16,
            "org_id": org_id,
        }
    }
    resp = client.post(f"{NEON_API}/projects", headers=headers(), json=payload)
    resp.raise_for_status()
    return resp.json()["project"]["id"]


def get_pooled_connection_uri(client, project_id: str) -> str:
    resp = client.get(
        f"{NEON_API}/projects/{project_id}/connection_uri",
        headers=headers(),
        params={"pooled": "true", "database_name": "neondb", "role_name": "neondb_owner"},
    )
    resp.raise_for_status()
    return resp.json()["uri"]


def main():
    with httpx.Client(timeout=60) as client:
        org_id = get_org_id(client)
        print(f"  ↪ Using org: {org_id}")

        project_id = find_existing_project(client, org_id)
        if project_id:
            print(f"  ↪ Reusing existing project '{PROJECT_NAME}' ({project_id})")
        else:
            project_id = create_project(client, org_id)
            print(f"  ✓ Created project '{PROJECT_NAME}' ({project_id})")

        uri = get_pooled_connection_uri(client, project_id)
        if "-pooler" not in uri:
            print("  ⚠ Warning: connection URI is not pooled. Mem0 may hit conn limits.")

        with open(".deploy.generated.env", "a") as f:
            f.write(f"DATABASE_URL='{uri}'\n")
        print("  ✓ DATABASE_URL written to .deploy.generated.env")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"  ❌ Neon API error: {e.response.status_code} {e.response.text}")
        sys.exit(1)
