from django.urls import reverse_lazy
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import StockItem


class StockListView(LoginRequiredMixin, ListView):
    model = StockItem
    template_name = 'inventory/stock_list.html'


class StockCreateView(LoginRequiredMixin, CreateView):
    model = StockItem
    fields = ['ingredient', 'warehouse', 'quantity', 'price']
    template_name = 'inventory/stock_form.html'
    success_url = reverse_lazy('inventory:stock_list')


class StockUpdateView(LoginRequiredMixin, UpdateView):
    model = StockItem
    fields = ['ingredient', 'warehouse', 'quantity', 'price']
    template_name = 'inventory/stock_form.html'
    success_url = reverse_lazy('inventory:stock_list')


class StockDeleteView(LoginRequiredMixin, DeleteView):
    model = StockItem
    template_name = 'inventory/stock_confirm_delete.html'
    success_url = reverse_lazy('inventory:stock_list')
from django.shortcuts import render

"""
Viewy související se skladem (např. stránka pro příjem zboží, automatické výdeje apod.).
CRUD pro zásoby je prozatím dostupný přes Django admin.
"""

# Create your views here.
