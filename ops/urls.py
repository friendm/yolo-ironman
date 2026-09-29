from django.urls import path

from . import views

app_name = "ops"

urlpatterns = [
    path("", views.queue, name="queue"),
    path("documents/<uuid:pk>", views.review, name="review"),
    path("documents/<uuid:pk>/agent-email", views.agent_verify, name="agent_verify"),
    path("documents/<uuid:pk>/remind", views.send_expiration_reminder, name="expiration_remind"),
    path("expirations", views.expirations, name="expirations"),
    path("directory", views.directory, name="directory"),
    path("vendors/<uuid:pk>", views.vendor_detail, name="vendor_detail"),
    path("document-types", views.document_types, name="document_types"),
    path("document-types/<uuid:pk>", views.document_types, name="document_type_edit"),
    path("templates", views.templates, name="templates"),
    path("templates/<uuid:pk>", views.templates, name="template_edit"),
    path("audit", views.audit_view, name="audit"),
    path("metrics", views.metrics_view, name="metrics"),
]
