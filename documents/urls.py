from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("documents/<uuid:pk>/file", views.view_document, name="view"),
    path("documents/<uuid:pk>/thumbnail", views.thumbnail, name="thumbnail"),
    path("files/<str:token>", views.signed_file, name="signed_file"),
    path("share/<str:token>", views.share, name="share"),
    path("share/<str:token>/<uuid:pk>", views.share_document, name="share_document"),
]
