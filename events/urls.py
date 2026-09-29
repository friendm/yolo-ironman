from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("org", views.org_home, name="org_home"),
    path("org/setup", views.org_setup, name="org_setup"),
    path("org/events/new", views.event_new, name="event_new"),
    path("org/events/<uuid:pk>", views.org_event, name="org_event"),
    path("org/events/<uuid:pk>/edit", views.event_edit, name="event_edit"),
    path("org/events/<uuid:pk>/invite", views.org_invite, name="org_invite"),
    path("org/events/<uuid:pk>/invite/vendor", views.org_invite_vendor, name="org_invite_vendor"),
    path("org/events/<uuid:pk>/vendors/<uuid:vendor_id>", views.org_vendor, name="org_vendor"),
    path("org/events/<uuid:pk>/remind", views.org_remind, name="org_remind"),
    path("org/events/<uuid:pk>/export.csv", views.export_csv, name="export_csv"),
    path("org/events/<uuid:pk>/export.zip", views.export_zip, name="export_zip"),
    path("i/<str:code>", views.invite, name="invite"),
    path("vendor/join", views.join, name="join"),
    path("vendor/join/<str:code>", views.join_code, name="join_code"),
    path("vendor/events/<uuid:pk>", views.vendor_event, name="vendor_event"),
    path("vendor/events/<uuid:pk>/additional-insured", views.ai_request, name="ai_request"),
    path("agent/upload/<str:token>", views.agent_upload, name="agent_upload"),
]
