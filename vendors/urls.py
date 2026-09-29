from django.urls import path

from . import views

app_name = "vendors"

urlpatterns = [
    path("", views.home, name="home"),
    path("basics", views.basics, name="basics"),
    path("documents", views.documents, name="documents"),
    path("documents/<slug:key>/upload", views.upload, name="upload"),
    path("documents/<uuid:pk>/confirm", views.confirm, name="confirm"),
    path("share", views.share, name="share"),
    path("share/<uuid:pk>/revoke", views.revoke_share, name="revoke_share"),
    path("account/delete", views.delete_account, name="delete_account"),
]
