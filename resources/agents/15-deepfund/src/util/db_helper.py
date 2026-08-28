from database.sqlite_helper import SQLiteDB
from database.supabase_helper import SupabaseDB
from util.logger import logger

# global variable that will be set in main.py
db = None

def db_initialize(use_local_db: bool = False):
    """Initialize the database connection based on the local-db flag."""
    global db
    if use_local_db:
        _db = SQLiteDB()
        logger.info("SQLite database initialized")
    else:
        _db = SupabaseDB()
        logger.info("Supabase database initialized")
    db = _db
    
def get_db():
    """Get the database instance."""
    return db

