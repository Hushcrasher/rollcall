from django.urls import URLPattern, URLResolver, path

from search import views

app_name = "search"

urlpatterns: list[URLPattern | URLResolver] = [
    path("", views.SearchView.as_view(), name="search"),
    path("suggest/", views.suggest, name="suggest"),
    path("games/", views.game_autocomplete, name="game_autocomplete"),
    path("companies/", views.company_autocomplete, name="company_autocomplete"),
    path("filters/engines/", views.engine_autocomplete, name="engine_autocomplete"),
    path("filters/genres/", views.genre_autocomplete, name="genre_autocomplete"),
    path("filters/countries/", views.country_autocomplete, name="country_autocomplete"),
    path("filters/games/", views.game_filter_autocomplete, name="game_filter_autocomplete"),
]
