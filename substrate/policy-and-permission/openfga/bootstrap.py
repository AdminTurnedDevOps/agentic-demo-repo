"""Seed an isolated OpenFGA store for the two existing counter Actors.

Run with the OpenFGA Service port-forwarded to localhost:8082. Requires only
Python's standard library plus kubectl/kubectl-ate on PATH.
"""

import json
import subprocess
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
FGA = "http://127.0.0.1:8082"


def run(*args, input_data=None):
    return subprocess.run(args, input=input_data, text=True, check=True, capture_output=True).stdout


def post(path, data):
    request = urllib.request.Request(
        FGA + path, json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def actor_uid(name):
    result = json.loads(run("kubectl", "ate", "get", "actor", name,
                            "-a", "ate-demo-counter", "-o", "json"))
    uid = result["actors"][0]["metadata"]["uid"]
    if not uid:
        raise ValueError("actor has no UID: " + name)
    return uid


def main():
    a, b = actor_uid("tool-a"), actor_uid("tool-b")
    store = post("/stores", {"name": "openfga-actors-lab"})["id"]
    model = post("/stores/" + store + "/authorization-models",
                 json.loads((ROOT / "model.json").read_text()))["authorization_model_id"]
    post("/stores/" + store + "/write", {
        "writes": {"tuple_keys": [
            {"user": "user:alice", "relation": "allowed_caller", "object": "actor:" + a},
        ]}, "authorization_model_id": model,
    })
    manifest = run("kubectl", "-n", "openfga-actors", "create", "configmap",
                   "openfga-actors-ids", "--from-literal=store=" + store,
                   "--from-literal=model=" + model, "--dry-run=client", "-o", "yaml")
    run("kubectl", "apply", "-f", "-", input_data=manifest)
    print("store:", store, "model:", model)
    print("tool-a:", a, "tool-b:", b)
    print("Alice can invoke tool-a. Bob and tool-b have no grant.")


if __name__ == "__main__":
    main()
