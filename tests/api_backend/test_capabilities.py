from backend.app.capabilities.builtins import BUILTIN_CAPABILITIES
from backend.app.questions.catalog import QUESTION_CATALOG


def test_builtin_capabilities_have_supported_question_ids() -> None:
    catalog_ids = {item['id'] for item in QUESTION_CATALOG}
    assert BUILTIN_CAPABILITIES
    for capability in BUILTIN_CAPABILITIES:
        assert capability.supported_question_ids
        assert set(capability.supported_question_ids).issubset(catalog_ids)
