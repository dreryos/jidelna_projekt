from django.http import HttpResponseForbidden
from django.core.exceptions import ObjectDoesNotExist


# Metody HTTP, které jsou povoleny i pro readonly uživatele
_SAFE_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# URL cesty, které jsou vždy povoleny (i pro readonly) bez ohledu na metodu
_ALWAYS_ALLOWED_PATHS = frozenset({
    '/accounts/logout/',
})


class ReadOnlyUserMiddleware:
    """
    Blokuje write operace (POST, PUT, PATCH, DELETE) pro uživatele s příznakem
    UserProfile.is_readonly == True.

    Superuseři a nepřihlášení uživatelé nejsou tímto middlewarem ovlivněni.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method not in _SAFE_METHODS
            and request.path not in _ALWAYS_ALLOWED_PATHS
            and request.user.is_authenticated
            and not request.user.is_superuser
        ):
            try:
                if request.user.profile.is_readonly:
                    return HttpResponseForbidden(
                        "Nemáte oprávnění k této akci. Váš účet má přístup pouze pro čtení."
                    )
            except ObjectDoesNotExist:
                pass

        return self.get_response(request)
