"""Names of the vectors stored per case in the operational_cases collection (QdrantInitializer).

    full        the whole case document (CaseDocumentBuilder.build) - free-text questions, collapsing
    symptom     what was seen (build_symptom) - "has this happened before?"
    resolution  cause and fix (build_resolution), only once a case has one - "where else did this fix work?"
    text        keywords of the whole document (sparse_encoder) - exact words in the ranking

Other collections (docs, findings, behaviors) keep a single unnamed dense vector.
"""

FULL_VECTOR = "full"
SYMPTOM_VECTOR = "symptom"
RESOLUTION_VECTOR = "resolution"
DENSE_VECTORS = (FULL_VECTOR, SYMPTOM_VECTOR, RESOLUTION_VECTOR)
# Every indexed case has these; resolution only once the case has a cause or fix.
ALWAYS_INDEXED = (FULL_VECTOR, SYMPTOM_VECTOR)
