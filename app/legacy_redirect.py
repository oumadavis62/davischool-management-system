from fastapi import Request
from fastapi.responses import RedirectResponse

def install_legacy_school_redirect(app):
    """Disable the legacy /school interface and send all traffic to the new DaviSchool UI."""
    @app.middleware("http")
    async def redirect_legacy_school(request: Request, call_next):
        path = request.url.path
        if path == "/school" or path.startswith("/school/"):
            return RedirectResponse("/app", status_code=303)
        return await call_next(request)
