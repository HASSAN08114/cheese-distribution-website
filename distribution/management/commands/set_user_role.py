from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from distribution.models import UserProfile


class Command(BaseCommand):
    help = 'Set user role (owner or employee)'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username')
        parser.add_argument('role', type=str, choices=['owner', 'employee'], help='Role: owner or employee')

    def handle(self, *args, **options):
        username = options['username']
        role = options['role']
        
        try:
            user = User.objects.get(username=username)
            profile, created = UserProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.save()
            
            if created:
                self.stdout.write(self.style.SUCCESS(f'Successfully created profile and set {username} as {role}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'Successfully updated {username} role to {role}'))
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" does not exist'))
