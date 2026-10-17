from django.urls import re_path
from .views.editor import EditorView
from .views.emails import SendCertificateEmailView
from .views.event_templates import (
    EventLayoutCreateView,
    EventLayoutDeleteView,
    EventLayoutListView,
    EventLayoutToggleView,
)
from .views.organizer import (
    OrganizerLayoutCreateView,
    OrganizerLayoutDeleteView,
    OrganizerLayoutListView,
)
from .views.positions import DownloadCertificateView, SendCertificateView

urlpatterns = [
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/editor(?:/layout/(?P<layout>\d+))?/?$",
        EditorView.as_view(),
        name="edit",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/$",
        EventLayoutListView.as_view(),
        name="layouts",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/add$",
        EventLayoutCreateView.as_view(),
        name="layouts.add",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/delete$",
        EventLayoutDeleteView.as_view(),
        name="layouts.delete",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/toggle$",
        EventLayoutToggleView.as_view(),
        name="layouts.toggle",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/$",
        OrganizerLayoutListView.as_view(),
        name="organizer.layouts",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/add$",
        OrganizerLayoutCreateView.as_view(),
        name="organizer.layouts.add",
    ),
    re_path(
        r"^control/organizer/(?P<organizer>[^/]+)/attendance-certificate/templates/(?P<layout>\d+)/delete$",
        OrganizerLayoutDeleteView.as_view(),
        name="organizer.layouts.delete",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sendmail/attendance-certificates/$",
        SendCertificateEmailView.as_view(),
        name="send",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/position/(?P<position>\d+)/download$",
        DownloadCertificateView.as_view(),
        name="position.download",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/position/(?P<position>\d+)/send$",
        SendCertificateView.as_view(),
        name="position.send",
    ),
]
