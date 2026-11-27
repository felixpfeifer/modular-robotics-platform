"""Read-only Hugging Face Hub browsing (list your models and datasets).

Uses the public REST API with the saved token. Nothing is downloaded here: large checkpoints
(GR00T is about 12 GB) are fetched by the serving or training container with its own token.
"""

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

API = "https://huggingface.co/api"
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
NAMESPACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")


class HubError(Exception):
    pass


def get_json(path, token, timeout=15):
    request = Request(API + path, headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise HubError("The Hugging Face token was rejected or lacks read access.") from exc
        raise HubError(f"Hugging Face returned HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise HubError(f"Cannot reach Hugging Face: {exc}") from exc


def namespaces(token, preferred=""):
    """The user's own name plus their organisations, or just the preferred namespace."""
    if preferred:
        if not NAMESPACE.fullmatch(preferred):
            raise HubError("Invalid namespace.")
        return [preferred]
    who = get_json("/whoami-v2", token)
    return [who["name"], *[org["name"] for org in who.get("orgs", []) if org.get("name")]]


def classify(tags, files):
    """Which container runtime a model repo is meant for, from its tags and file names."""
    names = {f.get("rfilename", "") for f in files}
    lowered = {t.lower() for t in tags}
    if (
        "gr00t" in lowered
        or any(t.startswith("gr00t") for t in lowered)
        or "experiment_cfg/metadata.json" in names
        or any(n.endswith("experiment_cfg/metadata.json") for n in names)
    ):
        return "groot"
    if "lerobot" in lowered or "config.json" in names and "policy_preprocessor.json" in names:
        return "lerobot_act"  # refined below to the exact policy type by the importer
    return "other"


def size_bytes(files):
    return sum(int(f.get("size") or 0) for f in files)


def list_repos(kind, token, preferred="", runtime=None):
    if kind not in ("models", "datasets"):
        raise HubError("kind must be models or datasets.")
    rows = []
    for author in namespaces(token, preferred):
        query = urlencode({"author": author, "full": "true", "limit": "100", "sort": "lastModified"})
        for item in get_json(f"/{kind}?{query}", token):
            files = item.get("siblings") or []
            entry = {
                "repo_id": item.get("id") or item.get("modelId"),
                "private": bool(item.get("private")),
                "updated": item.get("lastModified", ""),
                "size": size_bytes(files),
                "downloads": item.get("downloads", 0),
            }
            if not entry["repo_id"] or not REPO.fullmatch(entry["repo_id"]):
                continue
            if kind == "models":
                entry["runtime"] = classify(item.get("tags", []), files)
                if runtime and entry["runtime"] not in (runtime, "other"):
                    continue
            else:
                entry["lerobot"] = "lerobot" in {t.lower() for t in item.get("tags", [])}
            rows.append(entry)
    return rows


def repo_info(repo_id, token, revision=None):
    if not REPO.fullmatch(repo_id):
        raise HubError("Repository must use namespace/name syntax.")
    path = f"/models/{quote(repo_id, safe='/')}"
    if revision:
        path += f"/revision/{quote(revision, safe='')}"
    return get_json(path, token)
