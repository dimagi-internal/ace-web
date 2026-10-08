"""Email + password views — Django's own, with the ace-web additions.

Stock `LoginView`, `PasswordResetView`/`ConfirmView`, `PasswordChangeView`;
the additions are the shared admission gate (forms.EmailLoginForm), the
brute-force ceiling, session start through `identity.start_session`, and the
`ACE_PASSWORD_RESET_ENABLED` flag.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse_lazy

from apps.auth import google_oauth, identity
from apps.auth.forms import AdmittedPasswordResetForm, EmailLoginForm, limited


def script_prefix() -> str:
    return settings.FORCE_SCRIPT_NAME or ""


def home_url() -> str:
    return f"{script_prefix()}/"


def reset_enabled() -> bool:
    return bool(settings.ACE_PASSWORD_RESET_ENABLED)


class PasswordLoginView(auth_views.LoginView):
    """The login page: email + password form, plus Google and Connect buttons."""

    template_name = "auth/login.html"
    authentication_form = EmailLoginForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # resolve_url("/") would drop the /ace prefix and land on the ALB root.
        return home_url()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        next_url = self.get_redirect_url() or home_url()
        ctx.update(
            next=next_url,
            google_enabled=google_oauth.is_configured(),
            reset_enabled=reset_enabled(),
            show_test_login=bool(
                getattr(settings, "DEBUG", False)
                and getattr(settings, "ACE_ALLOW_TEST_LOGIN", False)
            ),
            test_login_url=f"{script_prefix()}/auth/test-login/",
            post_login_url=home_url(),
        )
        return ctx

    def form_valid(self, form):
        try:
            identity.start_session(self.request, form.get_user(), method=identity.METHOD_PASSWORD)
        except PermissionError:
            form.add_error(None, "This account is deactivated. Contact an administrator.")
            return self.form_invalid(form)
        return HttpResponseRedirect(self.get_success_url())


class _ResetGate:
    """404 the whole reset flow unless the flag is on."""

    def dispatch(self, request, *args, **kwargs):
        if not reset_enabled():
            raise Http404("Password reset is not enabled")
        return super().dispatch(request, *args, **kwargs)


class ResetRequestView(_ResetGate, auth_views.PasswordResetView):
    template_name = "auth/password_reset_form.html"
    email_template_name = "auth/password_reset_email.txt"
    subject_template_name = "auth/password_reset_subject.txt"
    form_class = AdmittedPasswordResetForm
    success_url = reverse_lazy("auth:password_reset_done")

    def form_valid(self, form):
        email = identity.normalize_email(form.cleaned_data["email"])
        if limited(self.request, "reset", email):
            # Answer exactly as if it had been sent: a distinct "slow down"
            # would tell an attacker which addresses they have already hit.
            return HttpResponseRedirect(self.get_success_url())
        return super().form_valid(form)


class ResetDoneView(_ResetGate, auth_views.PasswordResetDoneView):
    template_name = "auth/password_reset_done.html"


class ResetConfirmView(_ResetGate, auth_views.PasswordResetConfirmView):
    template_name = "auth/password_reset_confirm.html"
    success_url = reverse_lazy("auth:password_reset_complete")


class ResetCompleteView(_ResetGate, auth_views.PasswordResetCompleteView):
    template_name = "auth/password_reset_complete.html"


class PasswordSetOrChangeView(auth_views.PasswordChangeView):
    """Change a password — or, for an account that has none yet (it came in
    through Connect or Google), set the first one without an "old password"."""

    template_name = "auth/password_change.html"
    success_url = reverse_lazy("auth:account")

    def get_form_class(self):
        if self.request.user.has_usable_password():
            return PasswordChangeForm
        return SetPasswordForm

    def form_valid(self, form):
        messages.success(self.request, "Your password has been saved.")
        return super().form_valid(form)  # also keeps this session signed in


@login_required
def account(request):
    """Sign-in methods on this account: add a password, link Google."""
    user = request.user
    return render(request, "auth/account.html", {
        "has_password": user.has_usable_password(),
        "google_linked": bool(user.google_sub),
        "google_enabled": google_oauth.is_configured(),
        "login_method": request.session.get("ace_login_method", ""),
    })
