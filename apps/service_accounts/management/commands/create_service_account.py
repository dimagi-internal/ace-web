"""Management command to provision a service account from a credential file."""
from django.core.management.base import BaseCommand, CommandError

from apps.service_accounts.encryption import encrypt
from apps.service_accounts.models import ServiceAccount


class Command(BaseCommand):
    help = "Create a service account with credentials from a file."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Unique SA name")
        parser.add_argument(
            "--type", required=True, dest="credential_type",
            choices=["google_sa", "api_key"],
            help="Credential type",
        )
        parser.add_argument(
            "--credential-file", required=True, dest="credential_file",
            help="Path to the credential file (JSON key, API key text, etc.)",
        )
        parser.add_argument(
            "--scopes", nargs="*", default=[],
            help="Default scopes (space-separated)",
        )
        parser.add_argument(
            "--description", default="", help="Human-readable description",
        )

    def handle(self, **options):
        name = options["name"]
        if ServiceAccount.objects.filter(name=name).exists():
            raise CommandError(f"Service account {name!r} already exists.")

        try:
            with open(options["credential_file"]) as f:
                raw = f.read().strip()
        except FileNotFoundError as exc:
            raise CommandError(f"Credential file not found: {options['credential_file']}") from exc

        sa = ServiceAccount.objects.create(
            name=name,
            description=options["description"],
            credential_type=options["credential_type"],
            credential_encrypted=encrypt(raw),
            default_scopes=options["scopes"],
        )
        self.stdout.write(self.style.SUCCESS(
            f"Created service account {sa.name!r} (type={sa.credential_type})"
        ))
