from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health_check),
    path('chatbot/', views.ChatbotAPIView.as_view()),
    path('subscribers/', views.EmailSubscriberCreateAPIView.as_view()),
    path('blogs/', views.BlogPostListAPIView.as_view()),
    path('blogs/<int:pk>/', views.BlogPostDetailAPIView.as_view()),
    path('nav/', views.NavListAPIView.as_view()),
    path('nav/company-summary/', views.CompanyNavSummaryAPIView.as_view()),
    path('market-snapshot/', views.MarketSnapshotAPIView.as_view()),
]
