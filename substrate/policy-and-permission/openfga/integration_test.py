"""Test the real model against a local OpenFGA HTTP API on port 18082."""

import json
import urllib.request
from pathlib import Path


URL = "http://127.0.0.1:18082"


def post(path, body):
    req = urllib.request.Request(URL + path, json.dumps(body).encode(),
        {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def check(store, model, user, object_id):
    return post("/stores/" + store + "/check", {
        "authorization_model_id": model,
        "tuple_key": {"user": user, "relation": "can_invoke", "object": object_id},
    })["allowed"]


def main():
    store = post("/stores", {"name": "model-verification"})["id"]
    model = post("/stores/" + store + "/authorization-models",
        json.loads((Path(__file__).parent / "model.json").read_text()))["authorization_model_id"]
    tuple_key = {"user": "user:alice", "relation": "allowed_caller", "object": "actor:tool-a-uid"}
    post("/stores/" + store + "/write", {
        "authorization_model_id": model, "writes": {"tuple_keys": [tuple_key]}})
    assert check(store, model, "user:alice", "actor:tool-a-uid") is True
    assert check(store, model, "user:bob", "actor:tool-a-uid") is False
    assert check(store, model, "user:alice", "actor:tool-b-uid") is False
    post("/stores/" + store + "/write", {
        "authorization_model_id": model, "deletes": {"tuple_keys": [tuple_key]}})
    assert check(store, model, "user:alice", "actor:tool-a-uid") is False
    print("OpenFGA model checks: grant, deny, cross-target deny, revoke passed")


if __name__ == "__main__":
    main()
