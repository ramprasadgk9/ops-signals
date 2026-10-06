"""Near-copies fold under one match, so a recurring incident can't fill every slot.

A problem that happened five times the same way used to take all five Similar Cases slots, hiding
the one different past problem worth seeing. Here a match that is a near-copy of a higher-ranked one
- same service, and the whole case document (symptom, cause and fix) at least NEAR_COPY_SIMILARITY
alike - folds under it, shown as "+N more like this". Nothing is dropped; the history stays one
click away, and the novelty badge still counts every match.

Measured on case documents: two incidents with the same symptom, cause and fix score 0.97-0.98;
the same symptom fixed differently scores 0.86-0.92, so those stay separate.
"""

from __future__ import annotations

from backend.app.memory.vector_store import cosine_similarity

NEAR_COPY_SIMILARITY = 0.95


def collapse_near_copies(results: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Ranked search results (QdrantVectorStore.search, which returns each point's full-document
    `vector`) as (leader, near-copies) in rank order. A result without a vector is never folded."""
    groups: list[tuple[dict, list[dict]]] = []
    for result in results:
        vector = result.get("vector")
        service = (result.get("payload") or {}).get("service_key")
        for leader, copies in groups:
            leader_vector = leader.get("vector")
            if (
                vector and leader_vector
                and (leader.get("payload") or {}).get("service_key") == service
                and cosine_similarity(vector, leader_vector) >= NEAR_COPY_SIMILARITY
            ):
                copies.append(result)
                break
        else:
            groups.append((result, []))
    return groups


def leaders_only(results: list[dict]) -> list[dict]:
    """Ranked results with near-copies dropped, for lists that have no room to show them."""
    return [leader for leader, _ in collapse_near_copies(results)]
