from django import template
from ..decorators import is_owner as check_is_owner

register = template.Library()

@register.filter
def is_owner(user):
    """Template filter to check if user is owner"""
    return check_is_owner(user)
