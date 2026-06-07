from django.urls import re_path
from .views.editor import EditorView
from .views.emails import SendCertificateEmailView
from .views.positions import DownloadCertificateView, SendCertificateView

urlpatterns = [
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/attendance-certificate/editor",
        EditorView.as_view(),
        name="edit",
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
