from django.conf.urls import re_path
from .views.editor import EditorView
from .views.emails import SendCertificateEmailView

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
]
