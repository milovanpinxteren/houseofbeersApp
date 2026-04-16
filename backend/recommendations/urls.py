from django.urls import path
from . import views

urlpatterns = [
    # Recommendations
    path('', views.RecommendationsView.as_view(), name='recommendations'),
    path('profile/', views.TasteProfileView.as_view(), name='taste-profile'),
    path('styles/', views.StylesListView.as_view(), name='styles'),

    # Untappd linking
    path('untappd/', views.UntappdProfileView.as_view(), name='untappd-profile'),

    # Favorites
    path('favorites/', views.FavoritesListView.as_view(), name='favorites-list'),
    path('favorites/<int:favorite_id>/', views.FavoriteDetailView.as_view(), name='favorite-detail'),
    path('favorites/cart/', views.FavoritesCartLinkView.as_view(), name='favorites-cart'),
    path('favorites/cart/selected/', views.FavoritesSelectedCartLinkView.as_view(), name='favorites-cart-selected'),
]
