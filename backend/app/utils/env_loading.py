"""Project .env loading for standalone entry scripts (INFRA-12).

The simulation runner scripts load the project .env at import so a child
process started by the backend (or by hand) sees LLM_API_KEY and friends.  The
test suite imports those scripts at collection time, where the same call would
inject the developer's .env into the pytest process and steer every later
test.  ``load_project_dotenv`` is that load with one difference: it is a no-op
inside the test process (``DRF_TEST_PROCESS=1``, set by backend/tests/conftest.py
and never in production), mirroring the guard in app/config.py.
"""

import os

from dotenv import load_dotenv


def load_project_dotenv(path, *, override=False) -> bool:
    """Load ``path`` into os.environ; return True when the file exists and was loaded.

    ``override`` has load_dotenv's meaning (False keeps values already in the
    environment).  Returns False without touching os.environ when the file is
    missing or when running inside the test process.
    """
    if os.environ.get('DRF_TEST_PROCESS') == '1':
        return False
    if not path or not os.path.exists(path):
        return False
    load_dotenv(path, override=override)
    return True
