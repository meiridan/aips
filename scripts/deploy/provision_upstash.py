#!/usr/bin/env python3
"""Provision an Upstash Redis database via the Upstash REST API.
Idempotent: reuses an existing 'maya-redis' database if present.
Writes REDIS_URL to .deploy.generated.env.
"""
import os
import sys
import base64
import truststore
truststore.inject_into_ssl()
import httpx

UPSTASH_API = "https://api.upstash.com/v2/redis"
DB_NAME = "maya-redis"
REGION = "eu-west-1"


def auth():
    email = os.environ["UPSTASH_EMAIL"]
    key = os.environ["UPSTASH_API_KEY"]
    token = base64.b64encode(f"{email}:{key}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def find_existing(client) -> dict | None:
    resp = client.get(f"{UPSTASH_API}/databases", headers=auth())
    resp.raise_for_status()
    for db in resp.json():
        if db["database_name"] == DB_NAME:
            return db
    return None


def create_db(client) -> dict:
    payload = {
        "name": DB_NAME,
        "platform": "aws",
        "primary_region": REGION,
        "read_regions": [],
    }
    resp = client.post(f"{UPSTASH_API}/database", headers=auth(), json=payload)
    resp.raise_for_status()
    return resp.json()


def get_redis_info(client, db_id: str) -> dict:
    resp = client.get(f"{UPSTASH_API}/database/{db_id}", headers=auth())
    resp.raise_for_status()
    db = resp.json()
    endpoint = db["endpoint"]
    password = db["password"]
    rest_token = db["rest_token"]
    return {
        "redis_url": f"rediss://default:{password}@{endpoint}:6380",
        "rest_url": f"https://{endpoint}",
        "rest_token": rest_token,
    }


def main():
    with httpx.Client(timeout=60) as client:
        db = find_existing(client)
        if db:
            print(f"  ↪ Reusing existing Redis '{DB_NAME}'")
            db_id = db["database_id"]
        else:
            db = create_db(client)
            db_id = db["database_id"]
            print(f"  ✓ Created Redis '{DB_NAME}'")

        info = get_redis_info(client, db_id)
        with open(".deploy.generated.env", "a") as f:
            f.write(f"REDIS_URL='{info['redis_url']}'\n")
            f.write(f"UPSTASH_REDIS_REST_URL='{info['rest_url']}'\n")
            f.write(f"UPSTASH_REDIS_REST_TOKEN='{info['rest_token']}'\n")
        print("  ✓ REDIS_URL + REST credentials written to .deploy.generated.env")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPStatusError as e:
        print(f"  ❌ Upstash API error: {e.response.status_code} {e.response.text}")
        sys.exit(1)
