import psycopg2
from psycopg2 import Error
from contextlib import contextmanager
import os

try:
    from private import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
except ImportError as e:
    print(f"private.py not found or setup incorrectly: {e}")
    exit(1)


def get_connection(db_name=DB_NAME):
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=db_name,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        return conn
    except Error as e:
        return None


@contextmanager
def get_cursor(write=True, db_name=DB_NAME):
    conn = None
    cursor = None
    try:
        conn = get_connection(db_name)
        if conn is None:
            raise Exception("Failed to connect to database")
        cursor = conn.cursor()
        yield cursor
        if write:
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def test_connection(db_name=DB_NAME):
    conn = get_connection(db_name)
    if conn:
        conn.close()
        return True
    return False


def create_database():
    """Create the database if it doesn't exist. Returns True if exists or created."""
    conn = None
    try:
        conn = get_connection("postgres")
        if conn is None:
            print("Could not connect to PostgreSQL.")
            return False
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (DB_NAME,)
            )
            if cursor.fetchone():
                return True  # Already exists
            cursor.execute(f'CREATE DATABASE "{DB_NAME}"')
        print(f"Database '{DB_NAME}' created.")
        return True
    except Error as e:
        print(f"Error creating database: {e}")
        return False
    finally:
        if conn:
            conn.close()


def init_schema():
    """Initialize/update the database schema from ddl.sql."""
    ddl_path = os.path.join(os.path.dirname(__file__), "ddl.sql")
    
    if not os.path.exists(ddl_path):
        print(f"ddl.sql not found at {ddl_path}")
        return False
    
    try:
        with open(ddl_path, "r") as f:
            ddl_sql = f.read()
        
        conn = get_connection()
        if conn is None:
            print("Could not connect to database.")
            return False
        
        try:
            conn.autocommit = True
            with conn.cursor() as cursor:
                cursor.execute(ddl_sql)
            return True
        finally:
            conn.close()
            
    except Error as e:
        print(f"Error initializing schema: {e}")
        return False


def reset_database():
    """Drop ALL tables and recreate. WARNING: Deletes all data!"""
    try:
        conn = get_connection()
        if conn is None:
            return False
        
        conn.autocommit = True
        with conn.cursor() as cursor:
            cursor.execute("""
                DROP VIEW IF EXISTS activities_view CASCADE;
                DROP VIEW IF EXISTS tag_stats CASCADE;
                DROP VIEW IF EXISTS category_stats CASCADE;
                DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;
                DROP TABLE IF EXISTS activity_tags CASCADE;
                DROP TABLE IF EXISTS activities CASCADE;
                DROP TABLE IF EXISTS tags CASCADE;
                DROP TABLE IF EXISTS categories CASCADE;
            """)
        conn.close()
        print("All tables dropped.")
        return init_schema()
    except Error as e:
        print(f"Error resetting database: {e}")
        return False


def setup_database():
    """Full database setup: create database and initialize/update schema."""
    if not create_database():
        return False
    if not init_schema():
        return False
    print("Database ready.")
    return True


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        confirm = input("This will DELETE ALL DATA. Type 'yes' to confirm: ")
        if confirm.lower() == 'yes':
            if create_database():
                reset_database()
        else:
            print("Cancelled.")
    else:
        setup_database()