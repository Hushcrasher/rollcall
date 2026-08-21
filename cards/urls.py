from django.urls import path

from cards import views

app_name = "cards"

urlpatterns = [
    path("u/<slug:slug>/card.png", views.profile_card_view, name="profile"),
    path("g/<slug:slug>/card.png", views.game_card_view, name="game"),
    path("card.png", views.default_card_view, name="default"),
]
