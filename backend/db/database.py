"""
Firestore client for the storyteller database.

Usage
-----
    from backend.db.database import get_db, init_db

    # On startup:
    init_db()

    # Anywhere:
    db = get_db()
    db.collection("sessions").document("abc").set({...})
"""

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import Client as FirestoreClient

from backend.config import FIREBASE_CREDENTIALS, FIRESTORE_DATABASE_ID

_app: firebase_admin.App | None = None


def init_db() -> None:
    """Initialize the Firebase app (safe to call multiple times)."""
    global _app
    if _app is None:
        cred = credentials.Certificate(FIREBASE_CREDENTIALS)
        _app = firebase_admin.initialize_app(cred)


def get_db() -> FirestoreClient:
    """Return the Firestore client."""
    if _app is None:
        init_db()
    return firestore.client(app=_app, database_id=FIRESTORE_DATABASE_ID)
