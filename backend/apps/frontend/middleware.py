import importlib
import time
from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.sessions.backends.base import UpdateError
from django.contrib.sessions.exceptions import SessionInterrupted
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date


class DualSessionMiddleware(SessionMiddleware):
    """
    Dual Session Middleware:
    Maintains separate, isolated sessions for user/client workflows vs admin workflows.

    Routes under /admin, /django-admin, /dashboard, and /enterprise-admin use a dedicated
    session cookie (`admin_sessionid`), while all standard customer/client-facing routes
    use `sessionid`.

    This allows a developer, tester, or business owner to remain logged in as a normal client
    user in one tab (building/purchasing cards with their own client username) while
    simultaneously logged in as Super Admin or Staff in another tab without either session
    overwriting, logging out, or conflicting with the other.
    """

    ADMIN_PATH_PREFIXES = (
        '/admin',
        '/django-admin',
        '/dashboard',
        '/enterprise-admin',
    )

    def __init__(self, get_response):
        super().__init__(get_response)
        engine = importlib.import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore

    def is_admin_request(self, request):
        path = request.path_info or request.path or ''
        for prefix in self.ADMIN_PATH_PREFIXES:
            if path == prefix or path.startswith(f"{prefix}/"):
                return True
        return False

    def process_request(self, request):
        admin_cookie_name = getattr(settings, 'ADMIN_SESSION_COOKIE_NAME', 'admin_sessionid')
        user_cookie_name = settings.SESSION_COOKIE_NAME

        if self.is_admin_request(request):
            # Admin request:
            # 1. If admin_sessionid is present in request cookies, always use it.
            if admin_cookie_name in request.COOKIES:
                cookie_name = admin_cookie_name
                session_key = request.COOKIES.get(admin_cookie_name)
            elif (request.path_info or request.path or '').rstrip('/') == '/admin/login':
                # Dedicated admin login endpoint: always operate on admin_sessionid
                cookie_name = admin_cookie_name
                session_key = None
            elif user_cookie_name in request.COOKIES:
                # Fallback to user session cookie if admin cookie is not set yet
                # (supports test client force_login and staff users authenticated via client login)
                cookie_name = user_cookie_name
                session_key = request.COOKIES.get(user_cookie_name)
            else:
                cookie_name = admin_cookie_name
                session_key = None

            request._session_cookie_name = cookie_name
            request._is_admin_session = True
            request.session = self.SessionStore(session_key)
        else:
            # Standard client request:
            cookie_name = user_cookie_name
            request._session_cookie_name = cookie_name
            request._is_admin_session = False
            session_key = request.COOKIES.get(cookie_name)
            request.session = self.SessionStore(session_key)

    def process_response(self, request, response):
        """
        If request.session was modified, or if the configuration is to save the
        session every time, save the changes and set a session cookie or delete
        the session cookie if the session has been emptied.
        """
        try:
            accessed = request.session.accessed
            modified = request.session.modified
            empty = request.session.is_empty()
        except AttributeError:
            return response

        cookie_name = getattr(request, '_session_cookie_name', settings.SESSION_COOKIE_NAME)

        # First check if we need to delete this cookie.
        # The session should be deleted only if the session is entirely empty.
        if cookie_name in request.COOKIES and empty:
            response.delete_cookie(
                cookie_name,
                path=settings.SESSION_COOKIE_PATH,
                domain=settings.SESSION_COOKIE_DOMAIN,
                samesite=settings.SESSION_COOKIE_SAMESITE,
            )
            need_vary_cookie = True
        else:
            # If the session was accessed, it must be varied on, regardless of
            # whether it was modified or will be saved.
            need_vary_cookie = accessed
            if (modified or settings.SESSION_SAVE_EVERY_REQUEST) and not empty:
                if request.session.get_expire_at_browser_close():
                    max_age = None
                    expires = None
                else:
                    max_age = request.session.get_expiry_age()
                    expires_time = time.time() + max_age
                    expires = http_date(expires_time)
                # Save the session data and refresh the client cookie.
                # Skip session save for 5xx responses.
                if response.status_code < 500:
                    try:
                        request.session.save()
                    except UpdateError:
                        raise SessionInterrupted(
                            "The request's session was deleted before the "
                            "request completed. The user may have logged "
                            "out in a concurrent request, for example."
                        )
                    response.set_cookie(
                        cookie_name,
                        request.session.session_key,
                        max_age=max_age,
                        expires=expires,
                        domain=settings.SESSION_COOKIE_DOMAIN,
                        path=settings.SESSION_COOKIE_PATH,
                        secure=settings.SESSION_COOKIE_SECURE or None,
                        httponly=settings.SESSION_COOKIE_HTTPONLY or None,
                        samesite=settings.SESSION_COOKIE_SAMESITE,
                    )
                    need_vary_cookie = True
        if need_vary_cookie:
            patch_vary_headers(response, ("Cookie",))
        return response
