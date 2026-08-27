"""Schema 12 moves mkbrr's enable switch out of ``[general]``.

Every other ``[general]`` entry is a UI/workflow preference; this one only
means anything alongside the `mkbrr` path it governs, which lives in
`[dependencies]`. Moving it there also drops the "jump to Dependencies"
button that used to sit next to the checkbox in Settings -> General.
"""

from typing import Any

from src.config.migrations import migrate_v11_to_v12


def _doc(
    general: dict[str, Any] | None = None,
    dependencies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {"schema_version": 11}
    if general is not None:
        doc["general"] = general
    if dependencies is not None:
        doc["dependencies"] = dependencies
    return doc


def test_enable_mkbrr_moves_from_general_to_dependencies() -> None:
    document, unmapped = migrate_v11_to_v12(
        _doc(
            general={"timeout": 60, "enable_mkbrr": False},
            dependencies={"mkbrr": "/opt/mkbrr"},
        ),
        None,
    )

    assert not unmapped
    assert document["schema_version"] == 12
    assert "enable_mkbrr" not in document["general"]
    assert document["general"]["timeout"] == 60
    assert document["dependencies"] == {
        "mkbrr": "/opt/mkbrr",
        "enable_mkbrr": False,
    }


def test_an_enabled_value_is_preserved() -> None:
    document, _ = migrate_v11_to_v12(
        _doc(general={"enable_mkbrr": True}, dependencies={}),
        None,
    )

    assert document["dependencies"]["enable_mkbrr"] is True


def test_a_document_with_no_general_table_defaults_to_enabled() -> None:
    """Should not happen at schema 11 -- the packaged default always wrote the
    key -- but a corrupt/partial document must not crash the hop."""
    document, unmapped = migrate_v11_to_v12(
        _doc(dependencies={"mkbrr": ""}),
        None,
    )

    assert not unmapped
    assert document["dependencies"] == {"mkbrr": "", "enable_mkbrr": True}
    assert "general" not in document


def test_a_document_with_no_dependencies_table_still_migrates() -> None:
    document, unmapped = migrate_v11_to_v12(
        _doc(general={"enable_mkbrr": False}),
        None,
    )

    assert not unmapped
    assert document["dependencies"] == {"enable_mkbrr": False}


def test_everything_else_is_carried_forward_unchanged() -> None:
    document, _ = migrate_v11_to_v12(
        _doc(
            general={"enable_mkbrr": True, "releasers_name": "tester"},
            dependencies={"ffmpeg": "/usr/bin/ffmpeg"},
        ),
        None,
    )

    assert document["general"]["releasers_name"] == "tester"
    assert document["dependencies"]["ffmpeg"] == "/usr/bin/ffmpeg"


def test_a_document_with_neither_table_survives() -> None:
    document, unmapped = migrate_v11_to_v12({"schema_version": 11}, None)

    assert not unmapped
    assert document == {"schema_version": 12, "dependencies": {"enable_mkbrr": True}}
