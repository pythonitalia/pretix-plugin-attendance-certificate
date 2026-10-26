import datetime
import inspect

import pytest
from django.utils import translation
from django.utils.timezone import now
from django_scopes import scopes_disabled

from pretix.base.models import (
    Checkin,
    Event,
    Item,
    Order,
    OrderPosition,
    Organizer,
    Team,
    User,
)

from pretix_attendance_certificate.models import AttendanceCertificateLayout


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    """Disable django-scopes for all non-yield fixtures.

    Mirrors pretix' own test suite so fixtures can create scoped models
    (Order, OrderPosition, ...) without an active scope.
    """
    if inspect.isgeneratorfunction(fixturedef.func):
        yield
    else:
        with scopes_disabled():
            yield


@pytest.fixture(autouse=True)
def reset_locale():
    translation.activate("en")


@pytest.fixture
def event():
    organizer = Organizer.objects.create(name="Dummy", slug="dummy")
    event = Event.objects.create(
        organizer=organizer,
        name="Dummy",
        slug="dummy",
        date_from=now(),
        live=True,
        plugins="pretix_attendance_certificate",
    )
    return event


@pytest.fixture
def layout(event):
    return AttendanceCertificateLayout.objects.create(event=event, name="Default")


@pytest.fixture
def item(event):
    return Item.objects.create(
        name="Test item", event=event, default_price=13, admission=True
    )


@pytest.fixture
def order(event):
    return Order.objects.create(
        event=event,
        status=Order.STATUS_PAID,
        expires=now() + datetime.timedelta(hours=1),
        total=13,
        code="DUMMY",
        sales_channel=event.organizer.sales_channels.get(identifier="web"),
        email="dummy@dummy.test",
        datetime=now(),
        locale="en",
    )


@pytest.fixture
def pos(order, item):
    return OrderPosition.objects.create(
        order=order,
        item=item,
        price=13,
        attendee_name_parts={"_legacy": "Marco Acierno"},
        attendee_email="attendee@dummy.test",
    )


@pytest.fixture
def checkin(event, pos):
    checkin_list = event.checkin_lists.create(name="Default")
    return Checkin.objects.create(
        position=pos, list=checkin_list, type=Checkin.TYPE_ENTRY
    )


@pytest.fixture
def logged_in_client(client, event):
    user = User.objects.create_user("dummy@dummy.dummy", "dummy")
    team = Team.objects.create(
        organizer=event.organizer,
        limit_event_permissions={
            "event.orders:read": True,
            "event.orders:write": True,
        },
    )
    team.members.add(user)
    team.limit_events.add(event)
    client.force_login(user)
    return client


@pytest.fixture
def settings_client(client, event):
    user = User.objects.create_user("admin@dummy.dummy", "dummy")
    team = Team.objects.create(
        organizer=event.organizer,
        limit_event_permissions={"event.settings.general:write": True},
    )
    team.members.add(user)
    team.limit_events.add(event)
    client.force_login(user)
    return client
