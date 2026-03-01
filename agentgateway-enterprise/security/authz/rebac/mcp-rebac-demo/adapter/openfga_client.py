from __future__ import annotations

import requests


class OpenFGAClient:
    def __init__(self, url: str, store_id: str, model_id: str, timeout: float = 3.0):
        self.url = url.rstrip("/")
        self.store_id = store_id
        self.model_id = model_id
        self.timeout = timeout

    def _endpoint(self, path: str) -> str:
        return f"{self.url}/stores/{self.store_id}/{path.lstrip('/')}"

    def check(self, user: str, relation: str, obj: str, contextual: list[dict] | None = None) -> bool:
        payload = {
            "tuple_key": {"user": user, "relation": relation, "object": obj},
            "authorization_model_id": self.model_id,
        }
        if contextual:
            payload["contextual_tuples"] = {"tuple_keys": contextual}

        resp = requests.post(self._endpoint("check"), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return bool(resp.json().get("allowed", False))

    def list_objects(self, user: str, relation: str, type_name: str, contextual: list[dict] | None = None) -> list[str]:
        payload = {
            "user": user,
            "relation": relation,
            "type": type_name,
            "authorization_model_id": self.model_id,
        }
        if contextual:
            payload["contextual_tuples"] = {"tuple_keys": contextual}

        resp = requests.post(self._endpoint("list-objects"), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json().get("objects", [])
