from django.urls import URLPattern, URLResolver, path

from search import views

app_name = "search"

urlpatterns: list[URLPattern | URLResolver] = [
    path("games/", views.game_autocomplete, name="game_autocomplete"),
    path("companies/", views.company_autocomplete, name="company_autocomplete"),
]
