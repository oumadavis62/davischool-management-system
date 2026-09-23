# DaviSchool Management System

A secure browser-based school management platform designed for online deployment.

## Production architecture
- FastAPI application
- Managed PostgreSQL database
- HTTPS/TLS
- Secure signed sessions
- Audit log
- Role field for users
- Printable report cards
- Modules for students, staff, classes, subjects, assessments, marks, analytics, report cards, attendance, finance, timetable, library, inventory, discipline, parent messaging, exports and settings.

## Deployment validation
- The MarkSheet overall-metric selector uses syntax-safe Python string construction.
- The application source is validated by the repository Python compilation workflow before deployment.
- The current main branch contains the corrected `app/new_ui.py` MarkSheet selector.

## Local test
1. Install Python 3.12+.
2. Run `start_windows.bat`.
3. Open http://127.0.0.1:8000
4. Default local login: `admin` / `admin123` unless `ADMIN_USERNAME` and `ADMIN_PASSWORD` are set.

## Production deployment
This project includes `render.yaml`, `Dockerfile`, and `build.sh` for cloud deployment on Render. Render can provision the web service and PostgreSQL database, while managed TLS provides HTTPS for the public service.

Required production environment variables:
- `SECRET_KEY` — long random secret
- `ADMIN_USERNAME` — initial administrator username
- `ADMIN_PASSWORD` — initial administrator password
- `SCHOOL_NAME` — school name
- `SESSION_HTTPS=1` — secure session cookies when served over HTTPS
- `DATABASE_URL` — managed PostgreSQL URL (Render can inject this automatically)

After deployment, connect your custom domain (for example `davischool.co.ke`) in the hosting dashboard and configure its DNS. The host then issues/renews TLS and redirects HTTP to HTTPS.

## Important
The package is deployment-ready, but a real public domain/server cannot be provisioned from this chat without access to a cloud-hosting account and a domain owned by the school. Never send passwords, API keys, payment details, or hosting credentials in chat.
