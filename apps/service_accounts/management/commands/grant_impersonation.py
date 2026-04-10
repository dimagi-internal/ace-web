"""Management command to grant impersonation rights to a service account."""
from django.core.management.base import BaseCommand, CommandError

from apps.service_accounts.models import ImpersonationGrant, ServiceAccount


class Command(BaseCommand):
    help = "Grant impersonation rights to a service account."

    def add_arguments(self, parser):
        parser.add_argument("--sa", required=True, help="Service account name")
        parser.add_argument(
            "--subject", required=True,
            help="Email or pattern (e.g., alice@dimagi.com or *@dimagi.com)",
        )
        parser.add_argument(
            "--scopes", nargs="*", default=[],
            help="Allowed scopes for this grant (space-separated)",
        )

    def handle(self, **options):
        try:
            sa = ServiceAccount.objects.get(name=options["sa"])
        except ServiceAccount.DoesNotExist as exc:
            raise CommandError(f"Service account {options['sa']!r} not found.") from exc

        grant = ImpersonationGrant.objects.create(
            service_account=sa,
            subject_pattern=options["subject"],
            scopes=options["scopes"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Granted {sa.name!r} impersonation of {grant.subject_pattern!r}"
        ))
