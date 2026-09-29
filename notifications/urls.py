from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [path("hooks/twilio/inbound", views.twilio_inbound, name="twilio_inbound")]
