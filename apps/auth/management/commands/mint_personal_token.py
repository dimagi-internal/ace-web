"""Mint a PersonalToken (long-lived bearer PAT) for a user by email.

First-class, auditable way to issue a bot PAT — e.g. for the ACE automation
principal ace@dimagi-ai.com — WITHOUT the browser loopback flow
(/auth/cli/authorize/, which mints as whichever human is signed in). Run
server-side against the target deployment; the raw token is printed ONCE and
should be stored in the secret manager (1Password AI-Agents), then injected
into ACE's env as ACE_WEB_PAT_TOKEN.

Examples:
    # Mint ACE's own bot token (user must already exist — bots log in via OAuth first):
    python manage.py mint_personal_token --email ace@dimagi-ai.com --label ace-bot

    # Rotate: revoke any existing active tokens with the same label, then mint fresh:
    python manage.py mint_personal_token --email ace@dimagi-ai.com --label ace-bot --rotate

    # Bootstrap a brand-new principal (creates the User if absent):
    python manage.py mint_personal_token --email ace@dimagi-ai.com --label ace-bot --create-user
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.auth.models import PersonalToken, User


class Command(BaseCommand):
    help = "Mint a PersonalToken (bearer PAT) for a user by email. Prints the raw token once."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="User email to mint the token for.")
        parser.add_argument(
            "--label", default="ace-bot",
            help="Token label (shown in the token list). Default: ace-bot.",
        )
        parser.add_argument(
            "--rotate", action="store_true",
            help="Revoke existing active tokens with the same label for this user before minting.",
        )
        parser.add_argument(
            "--create-user", action="store_true",
            help="Create the User if it does not exist (bootstrap a new principal).",
        )

    def handle(self, **options):
        email = options["email"].strip()
        label = options["label"].strip()[:200]
        if not label:
            raise CommandError("--label must be non-empty")

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            if not options["create_user"]:
                raise CommandError(
                    f"No user with email {email!r}. A principal normally logs in via OAuth first; "
                    f"pass --create-user to bootstrap one explicitly."
                )
            user = User.objects.create(
                email=email,
                display_name=email.split("@", 1)[0],
            )
            self.stdout.write(self.style.WARNING(f"Created user {email!r}."))

        if options["rotate"]:
            revoked = (
                PersonalToken.objects
                .filter(user=user, label=label, revoked_at__isnull=True)
                .update(revoked_at=timezone.now())
            )
            if revoked:
                self.stdout.write(self.style.WARNING(
                    f"Revoked {revoked} existing active token(s) labelled {label!r}."
                ))

        raw, token = PersonalToken.create_for_user(user=user, label=label)
        self.stdout.write(self.style.SUCCESS(
            f"Minted PersonalToken for {user.email} (label={label!r}, pk={token.pk})."
        ))
        self.stdout.write("")
        self.stdout.write("Raw token (shown ONCE — store it in 1Password now):")
        self.stdout.write(raw)
