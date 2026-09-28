"""Grant, revoke, or check Alice/Bob access to the current Actor UID.

Requires kubectl-ate and a port-forward for svc/openfga on localhost:8082.
"""

import argparse
import json
import subprocess
import urllib.request


def output(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def request(path, body):
    req = urllib.request.Request("http://127.0.0.1:8082" + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.load(res)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("grant", "revoke", "check"))
    parser.add_argument("caller", choices=("alice", "bob"))
    parser.add_argument("target", choices=("tool-a", "tool-b"))
    args = parser.parse_args()
    ids = json.loads(output("kubectl", "-n", "openfga-actors", "get", "configmap",
                            "openfga-actors-ids", "-o", "json"))["data"]
    actor = json.loads(output("kubectl", "ate", "get", "actor", args.target,
                              "-a", "ate-demo-counter", "-o", "json"))
    uid = actor["actors"][0]["metadata"]["uid"]
    tuple_key = {"user": "user:" + args.caller, "relation": "allowed_caller",
                 "object": "actor:" + uid}
    prefix = "/stores/" + ids["store"]
    if args.action == "check":
        print(request(prefix + "/check", {"authorization_model_id": ids["model"],
            "tuple_key": {**tuple_key, "relation": "can_invoke"}}))
    else:
        key = "writes" if args.action == "grant" else "deletes"
        request(prefix + "/write", {"authorization_model_id": ids["model"],
            key: {"tuple_keys": [tuple_key]}})
        print(args.action, tuple_key)


if __name__ == "__main__":
    main()
