import subprocess
from datetime import datetime
from django.contrib.sessions.models import Session
from django.utils import timezone

_app_version = None


def active_users_count(request):
    """
    Vrací počet aktuálně přihlášených uživatelů na základě aktivních session.
    """
    try:
        # Získáme všechny aktivní session (ještě nevypršel platnost)
        active_sessions = Session.objects.filter(expire_date__gte=timezone.now())
        
        # Pro každou session získáme user_id z dat
        user_ids = set()
        for session in active_sessions:
            session_data = session.get_decoded()
            user_id = session_data.get('_auth_user_id')
            if user_id:
                user_ids.add(user_id)
        
        return {'active_users_count': len(user_ids)}
    except Exception:
        # V případě chyby vrátíme 0
        return {'active_users_count': 0}


def app_version(request):
    global _app_version
    if _app_version is None:
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%cd', '--date=format:%d%m%y'],
                capture_output=True,
                text=True,
                timeout=2,
            )
            version = result.stdout.strip()
            _app_version = version if version else datetime.today().strftime('%d%m%y')
        except Exception:
            _app_version = datetime.today().strftime('%d%m%y')
    return {'app_version': _app_version}
