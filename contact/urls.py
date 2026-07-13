from django.urls import URLPattern, URLResolver, path

from contact import views

app_name = "contact"

urlpatterns: list[URLPattern | URLResolver] = [
    path("contact/<slug:slug>/", views.ContactView.as_view(), name="contact"),
]
