#!/usr/bin/env python3
"""Delete all provisioned resources. Use with caution.
Prompts for confirmation before deleting.
"""
import os
import sys
import base64
import truststore
truststore.inject_into_ssl()
import httpx


def confirm():
    ans = input("⚠ This deletes Neon + Upstash + Railway resources. Type 'DELETE' to confirm: ")
    if ans != "DELETE":
        print("Aborted.")
        sys.exit(0)


def teardown_neon(client):
    key = os.environ["NEON_API_KEY"]
    h = {"Authorization": f"Bearer {key}"}
    resp = client.get("https://console.neon.tech/api/v2/projects", headers=h)
    for p in resp.json().get("projects", []):
        if p["name"] == "maya-core":
            client.delete(f"https://console.neon.tech/api/v2/projects/{p['id']}", headers=h)
            print(f"  ✓ Deleted Neon project {p['id']}")


def teardown_upstash(client):
    email = os.environ["UPSTASH_EMAIL"]
    key = os.environ["UPSTASH_API_KEY"]
    token = base64.b64encode(f"{email}:{key}".encode()).decode()
    h = {"Authorization": f"Basic {token}"}
    resp = client.get("https://api.upstash.com/v2/redis/databases", headers=h)
    for db in resp.json():
        if db["database_name"] == "maya-redis":
            client.delete(f"https://api.upstash.com/v2/redis/database/{db['database_id']}", headers=h)
            print(f"  ✓ Deleted Upstash DB {db['database_id']}")


def main():
    from dotenv import load_dotenv
    load_dotenv(".deploy.env")
    confirm()
    with httpx.Client(timeout=60) as client:
        teardown_neon(client)
        teardown_upstash(client)
    print("\n  ℹ Railway: run 'railway down' manually to remove the project.")
    print("  ✓ Teardown complete.")


if __name__ == "__main__":
    main()
