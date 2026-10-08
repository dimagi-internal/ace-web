"""Forms for email + password sign-in, reset and invite password-setting."""
from __future__ import annotations

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm

from apps.auth import identity
from apps.auth.login_gate import admission_rule
from apps.auth.models import User
from apps.common.rate_limit import allow, client_ip

TOO_MANY = "Too many attempts. Please wait a few minutes and try again."


def limited(request, kind: str, email: str) -> bool:
    """Charge one attempt to the per-address AND per-email buckets for `kind`.

    True when either is spent. Both are always charged (no short-circuit) so a
    caller cannot learn which one tripped.
    """
    ip_limit = getattr(settings, f"ACE_{kind.upper()}_RATE_LIMIT_IP")
    email_limit = getattr(settings, f"ACE_{kind.upper()}_RATE_LIMIT_EMAIL")
    ok_ip = allow(f"{kind}:ip:{client_ip(request)}", limit=ip_limit[0], window_seconds=ip_limit[1])
    ok_email = allow(f"{kind}:email:{email}", limit=email_limit[0], window_seconds=email_limit[1])
    return not (ok_ip and ok_email)


class EmailLoginForm(AuthenticationForm):
    """Django's AuthenticationForm + brute-force ceiling + the admission gate."""

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "type": "email", "autofocus": True}
        )
        self.fields["password"].widget.attrs.update({"autocomplete": "current-password"})

    def clean(self):
        email = identity.normalize_email(self.cleaned_data.get("username"))
        if email and limited(self.request, "login", email):
            raise forms.ValidationError(TOO_MANY, code="rate_limited")
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)  # is_active
        # Same gate as Google and Connect. Runs only AFTER the password
        # verified, so the refusal says nothing to someone guessing.
        if not identity.admit(user.email, method=identity.METHOD_PASSWORD):
            raise forms.ValidationError(identity.not_admitted_message(), code="not_admitted")


class AdmittedPasswordResetForm(PasswordResetForm):
    """Only active, password-holding users who would still be admitted get mail."""

    def get_users(self, email):
        for user in super().get_users(email):
            if admission_rule(user.email) is not None:
                yield user


class InvitePasswordForm(forms.Form):
    """Choose a password to accept a workspace invite (no account exists yet)."""

    password1 = forms.CharField(
        label="Password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=password_validation.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        label="Confirm password", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, email: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.email = email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "The two passwords don't match.")
            else:
                # An unsaved User so UserAttributeSimilarityValidator sees the email.
                password_validation.validate_password(p1, User(email=self.email))
        return cleaned
