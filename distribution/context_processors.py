from .decorators import is_owner

def user_role(request):
    """Context processor to add user role information to all templates"""
    if request.user.is_authenticated:
        return {
            'user_is_owner': is_owner(request.user),
        }
    return {
        'user_is_owner': False,
    }
