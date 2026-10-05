import subprocess
from datetime import datetime

_app_version = None


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
