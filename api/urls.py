from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health_check),
    path('nav/', views.NavListAPIView.as_view()),
    path('nav/company-summary/', views.CompanyNavSummaryAPIView.as_view()),
]
