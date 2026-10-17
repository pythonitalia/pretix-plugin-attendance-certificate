import pytest
from django.core.files.base import ContentFile
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import Event, Organizer
from pretix.base.signals import event_copy_data


def _new_event(organizer, slug="copy"):
    return Event.objects.create(
        organizer=organizer,
        name="Copy",
        slug=slug,
        date_from=now(),
        live=True,
        plugins="pretix_attendance_certificate",
    )


@pytest.mark.django_db
def test_event_copy_copies_event_owned_layout(event, layout):
    with scopes_disabled():
        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        copied = new_event.attendance_certificate_layouts.get()
        assert copied.pk != layout.pk
        assert copied.name == layout.name
        assert str(copied.mail_subject) == str(layout.mail_subject)
        assert str(copied.mail_text) == str(layout.mail_text)
        # The source event's own layout must be untouched.
        assert event.attendance_certificate_layouts.get().pk == layout.pk


@pytest.mark.django_db
def test_event_copy_copies_background_file_independently(event, layout):
    with scopes_disabled():
        layout.background.save("background.pdf", ContentFile(b"%PDF-fake"))
        old_background_name = layout.background.name

        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        copied = new_event.attendance_certificate_layouts.get()
        assert copied.background.name
        assert copied.background.name != old_background_name


@pytest.mark.django_db
def test_event_copy_copies_organizer_layout_activation(event, organizer_layout):
    with scopes_disabled():
        organizer_layout.active_events.add(event)

        new_event = _new_event(event.organizer)
        event_copy_data.send(sender=new_event, other=event)

        assert organizer_layout.active_events.filter(pk=new_event.pk).exists()
        # Still activated for the original event too - not moved, copied.
        assert organizer_layout.active_events.filter(pk=event.pk).exists()


@pytest.mark.django_db
def test_event_copy_skips_activation_across_organizers(event, organizer_layout):
    with scopes_disabled():
        organizer_layout.active_events.add(event)
        other_organizer = Organizer.objects.create(name="Other", slug="other")
        new_event = _new_event(other_organizer, slug="other-event")

        event_copy_data.send(sender=new_event, other=event)

        assert not organizer_layout.active_events.filter(pk=new_event.pk).exists()
