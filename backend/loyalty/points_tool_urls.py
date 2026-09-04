"""URL map of the Puntentool, mounted at /admin/points-tool/."""
from django.urls import path

from . import points_tool_views, studio_views

app_name = 'points_tool'

urlpatterns = [
    path('', points_tool_views.index, name='index'),
    # The Studio's member search is exactly this tool's member search, so it is
    # mounted here as-is instead of being copied. Registering the same view
    # under a second name leaves studio:user_search untouched.
    path('user-search/', studio_views.user_search, name='user_search'),
    path('<int:user_id>/', points_tool_views.member, name='member'),
]
