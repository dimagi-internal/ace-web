from django.contrib.auth.base_user import BaseUserManager


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, display_name: str = "", google_sub: str | None = None):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        # Coerce empty string to None — an empty `google_sub` would violate
        # the UNIQUE constraint on the second user created without a sub.
        user = self.model(
            email=email,
            display_name=display_name or email.split("@")[0],
            google_sub=google_sub or None,
        )
        user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None):
        user = self.create_user(email=email, display_name=email.split("@")[0])
        user.is_staff = True
        user.is_superuser = True
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user
