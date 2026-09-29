from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("vendor/start", views.vendor_start, name="vendor_start"),
    path("org/start", views.org_start, name="org_start"),
    path("login", views.login_view, name="login"),
    path("login/code", views.enter_code, name="code"),
    path("login/email", views.email_login, name="email_login"),
    path("login/email-link", views.email_link, name="email_link"),
    path("login/magic/<str:token>", views.magic, name="magic"),
    path("welcome", views.choose_role, name="choose_role"),
    path("logout", views.logout_view, name="logout"),
    path("terms", views.terms, name="terms"),
    path("privacy", views.privacy, name="privacy"),
]
