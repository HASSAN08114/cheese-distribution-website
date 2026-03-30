from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .models import UserProfile


def owner_required(view_func):
    """Decorator to ensure only owners can access a view"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login to access this page.')
            return redirect('login')
        try:
            profile = UserProfile.objects.get(user=request.user)
            if not profile.is_owner():
                messages.error(request, 'You do not have permission to access this page.')
                return redirect('inventory_management')
        except UserProfile.DoesNotExist:
            messages.error(request, 'Your account is not properly configured. Please contact administrator.')
            return redirect('inventory_management')
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def get_user_role(user):
    """Helper function to get user role"""
    try:
        profile = UserProfile.objects.get(user=user)
        return profile.role
    except UserProfile.DoesNotExist:
        return 'employee'  # Default to employee if profile doesn't exist


def is_owner(user):
    """Helper function to check if user is owner"""
    try:
        profile = UserProfile.objects.get(user=user)
        return profile.is_owner()
    except UserProfile.DoesNotExist:
        return False
