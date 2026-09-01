from uuid import UUID

from drift.domain.ids import new_entity_id, new_event_id


def test_generated_ids_are_uuid7() -> None:
    assert new_entity_id().version == 7
    assert new_event_id().version == 7


def test_generated_ids_are_uuid_instances() -> None:
    assert isinstance(new_entity_id(), UUID)
    assert isinstance(new_event_id(), UUID)
