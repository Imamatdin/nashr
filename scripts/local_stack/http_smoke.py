"""HTTP-level evidence journey against the local stack (no browser).

Upload -> register -> process -> passages -> cite -> save -> DOCX, plus a
corrupt source and cross-user isolation. Exits non-zero on the first failure.
"""

from __future__ import annotations

import io
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from docx import Document

API = "http://127.0.0.1:8090"


def upload(client: httpx.Client, project: str, path: Path) -> dict[str, object]:
    """Presign, PUT bytes to the S3 stand-in, and register the source."""

    data = path.read_bytes()
    presign = client.post(
        "/sources/presign", json={"project_id": project, "filename": path.name, "size_bytes": len(data)}
    )
    presign.raise_for_status()
    ticket = presign.json()
    put = httpx.put(ticket["upload_url"], content=data, headers={"Content-Type": ticket["content_type"]})
    put.raise_for_status()
    registered = client.post(
        "/sources", json={"project_id": project, "storage_key": ticket["storage_key"], "filename": path.name}
    )
    registered.raise_for_status()
    return registered.json()


def wait_for_job(client: httpx.Client, project: str) -> dict[str, object]:
    """Poll the evidence view until processing is terminal."""

    for _ in range(90):
        view = client.get(f"/projects/{project}/evidence").json()
        if view["job"] and view["job"]["status"] in {"completed", "failed"}:
            return view
        time.sleep(1)
    raise TimeoutError("source processing did not finish")


def main(fixture_json: str, fixtures_dir: str) -> None:
    """Run the journey for the UZ project with a PDF, a DOCX and a corrupt file."""

    fixture = json.loads(Path(fixture_json).read_text(encoding="utf-8"))
    project = fixture["projects"]["uz"]
    auth = {"Authorization": f"Bearer {fixture['session']['accessToken']}"}
    client = httpx.Client(base_url=API, headers=auth, timeout=60)
    files = Path(fixtures_dir)
    for name in ["orol-dengizi-tarixi.pdf", "аральское-море.docx", "buzilgan-manba.pdf"]:
        try:
            source = upload(client, project, files / name)
            print("registered", name, source["id"])
        except httpx.HTTPStatusError as exc:
            print("register refused", name, exc.response.status_code, exc.response.text[:200])
    queued = client.post(f"/projects/{project}/evidence/process")
    print("process", queued.status_code, queued.json().get("status"))
    view = wait_for_job(client, project)
    print("job", view["job"]["status"], json.dumps(view["job"]["progress"]), view["job"]["error_message"])
    for source in view["sources"]:
        print("source", source["filename"], source["processed_at"] is not None, source["passage_count"])
    passages = view["passages"]
    print("passages", len(passages), [(p["page"], p["text"][:40]) for p in passages[:4]])
    assert passages, "no passages extracted"

    intruder = httpx.Client(
        base_url=API, headers={"Authorization": f"Bearer {fixture['intruderToken']}"}, timeout=30
    )
    print("intruder evidence", intruder.get(f"/projects/{project}/evidence").status_code)
    print("intruder passage", intruder.get(f"/projects/{project}/evidence/passages/{passages[0]['id']}").status_code)

    article = client.post(
        f"/projects/{project}/documents/article", json={"title": "Orol", "idempotency_key": f"init:{project}"}
    ).json()
    first = passages[0]
    block = {
        "id": str(uuid.uuid4()), "type": "paragraph", "level": None,
        "text": "Orol dengizi 1960-yildan beri qurimoqda.",
        "citations": [{"source_id": first["source_id"], "passage_id": first["id"], "claim_id": None, "label": " x "}],
    }
    content = {"kind": "article", "schema_version": 1, "title": "Orol dengizi", "blocks": [block]}
    key = str(uuid.uuid4())
    saved = client.put(
        f"/projects/{project}/documents/article",
        json={"base_revision_id": article["revision_id"], "idempotency_key": key, "content": content},
    )
    print("save", saved.status_code, saved.json()["content"]["blocks"][0]["citations"][0]["label"])
    replay = client.put(
        f"/projects/{project}/documents/article",
        json={"base_revision_id": article["revision_id"], "idempotency_key": key, "content": content},
    )
    print("replay same key", replay.status_code, replay.json()["revision_id"] == saved.json()["revision_id"])
    stale = client.put(
        f"/projects/{project}/documents/article",
        json={"base_revision_id": article["revision_id"], "idempotency_key": str(uuid.uuid4()), "content": content},
    )
    print("stale base", stale.status_code, stale.text[:80])
    foreign = dict(block, id=str(uuid.uuid4()), citations=[dict(block["citations"][0], passage_id=str(uuid.uuid4()))])
    rejected = client.put(
        f"/projects/{project}/documents/article",
        json={"base_revision_id": saved.json()["revision_id"], "idempotency_key": str(uuid.uuid4()),
              "content": dict(content, blocks=[foreign])},
    )
    print("unknown passage", rejected.status_code, rejected.text[:80])
    exported = client.get(
        f"/projects/{project}/documents/article/export.docx", params={"revision_id": saved.json()["revision_id"]}
    )
    text = "\n".join(p.text for p in Document(io.BytesIO(exported.content)).paragraphs)
    print("docx", exported.status_code, exported.headers.get("x-document-revision") == saved.json()["revision_id"])
    print("docx text", text.replace("\n", " | ")[:300])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
