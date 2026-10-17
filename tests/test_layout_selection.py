import pytest
from django_scopes import scopes_disabled

from pretix_attendance_certificate.models import (
    AttendanceCertificateLayout,
    available_layouts,
)


@pytest.mark.django_db
def test_str_shows_name_not_object_repr(layout):
    layout.name = "Teilnahmebestätigung"
    assert str(layout) == "Teilnahmebestätigung"


@pytest.mark.django_db
def test_single_event_owned_layout_is_available(event, layout):
    assert list(available_layouts(event)) == [layout]


@pytest.mark.django_db
def test_organizer_layout_not_available_until_activated(event, layout, organizer_layout):
    assert list(available_layouts(event)) == [layout]

    with scopes_disabled():
        organizer_layout.active_events.add(event)

    assert set(available_layouts(event)) == {layout, organizer_layout}


@pytest.mark.django_db
def test_multiple_activated_organizer_layouts(
    event, layout, organizer_layout, second_organizer_layout
):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
        second_organizer_layout.active_events.add(event)

    assert set(available_layouts(event)) == {
        layout,
        organizer_layout,
        second_organizer_layout,
    }


@pytest.mark.django_db
def test_no_candidates_when_everything_deactivated_or_deleted(event, layout):
    with scopes_disabled():
        layout.delete()

    assert list(available_layouts(event)) == []


@pytest.mark.django_db
def test_organizer_layout_scoped_to_its_own_events(event, organizer_layout):
    with scopes_disabled():
        from pretix.base.models import Event
        from django.utils.timezone import now

        other_event = Event.objects.create(
            organizer=event.organizer,
            name="Other",
            slug="other",
            date_from=now(),
            live=True,
            plugins="pretix_attendance_certificate",
        )
        organizer_layout.active_events.add(event)

    assert list(available_layouts(event)) == [organizer_layout]
    assert list(available_layouts(other_event)) == []


@pytest.mark.django_db
def test_visible_to_includes_inactive_organizer_layouts(event, layout, organizer_layout):
    # visible_to() is used for permission scoping (e.g. editing), so it must
    # include organizer-wide layouts even before they are activated for this
    # specific event - unlike available_layouts().
    visible = set(AttendanceCertificateLayout.visible_to(event))
    assert visible == {layout, organizer_layout}
