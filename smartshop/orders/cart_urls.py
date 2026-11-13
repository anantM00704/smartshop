from django.urls import path

from . import views

urlpatterns = [
    path('', views.cart, name='cart'),
    path('add/', views.cart_add, name='cart_add'),
    path('items/<int:item_id>/update/', views.cart_update, name='cart_update'),
    path('items/<int:item_id>/remove/', views.cart_remove, name='cart_remove'),
    path('checkout/', views.checkout, name='checkout'),
]