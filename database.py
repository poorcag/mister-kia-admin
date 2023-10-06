# Copyright 2021 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

import datetime
import os
from typing import Any

import sqlalchemy
from sqlalchemy.orm import close_all_sessions
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import IntegrityError

import credentials
from middleware import logger

# This global variable is declared with a value of `None`, instead of calling
# `init_connection_engine()` immediately, to simplify testing. In general, it
# is safe to initialize your database connection pool when your script starts
# -- there is no need to wait for the first request.
db = None


def init_connection_engine() -> sqlalchemy.engine.base.Engine:
    """Initializes a connection pool for a Cloud SQL instance of PostgreSQL.

    Returns:
        A SQLAlchemy Engine instance.
    """
    if os.getenv("TRAMPOLINE_CI", None):
        logger.info("Using NullPool for testing")
        db_config: dict[str, Any] = {"poolclass": NullPool}
    else:
        db_config: dict[str, Any] = {
            # Pool size is the maximum number of permanent connections to keep.
            "pool_size": 5,
            # Temporarily exceeds the set pool_size if no connections are available.
            "max_overflow": 2,
            # The total number of concurrent connections for your application will be
            # a total of pool_size and max_overflow.
            # SQLAlchemy automatically uses delays between failed connection attempts,
            # but provides no arguments for configuration.
            # 'pool_timeout' is the maximum number of seconds to wait when retrieving a
            # new connection from the pool. After the specified amount of time, an
            # exception will be thrown.
            "pool_timeout": 30,  # 30 seconds
            # 'pool_recycle' is the maximum number of seconds a connection can persist.
            # Connections that live longer than the specified amount of time will be
            # reestablished
            "pool_recycle": 1800,  # 30 minutes
        }

    if os.environ.get("DB_HOST"):
        return init_tcp_connection_engine(db_config)
    else:
        return init_unix_connection_engine(db_config)


def init_tcp_connection_engine(
    db_config: dict[str, type[NullPool]]
) -> sqlalchemy.engine.base.Engine:
    """Initializes a TCP connection pool for a Cloud SQL instance of PostgreSQL.

    Args:
        db_config: a dictionary with connection pool config

    Returns:
        A SQLAlchemy Engine instance.
    """
    creds = credentials.get_cred_config()
    db_user = creds["DB_USER"]
    db_pass = creds["DB_PASSWORD"]
    db_name = creds["DB_NAME"]
    db_host = creds["DB_HOST"]

    # Extract host and port from db_host
    host_args = db_host.split(":")
    db_hostname, db_port = host_args[0], int(host_args[1])

    pool = sqlalchemy.create_engine(
        # Equivalent URL:
        # postgres+pg8000://<db_user>:<db_pass>@<db_host>:<db_port>/<db_name>
        sqlalchemy.engine.url.URL.create(
            drivername="postgresql+pg8000",
            username=db_user,  # e.g. "my-database-user"
            password=db_pass,  # e.g. "my-database-password"
            host=db_hostname,  # e.g. "127.0.0.1"
            port=db_port,  # e.g. 5432
            database=db_name,  # e.g. "my-database-name"
        ),
        **db_config,
    )
    pool.dialect.description_encoding = None
    logger.info("Database engine initialized from tcp connection")

    return pool


# [START cloudrun_user_auth_sql_connect]
def init_unix_connection_engine(
    db_config: dict[str, int]
) -> sqlalchemy.engine.base.Engine:
    """Initializes a Unix socket connection pool for a Cloud SQL instance of PostgreSQL.

    Args:
        db_config: a dictionary with connection pool config

    Returns:
        A SQLAlchemy Engine instance.
    """
    creds = credentials.get_cred_config()
    db_user = creds["DB_USER"]
    db_pass = creds["DB_PASSWORD"]
    db_name = creds["DB_NAME"]
    db_socket_dir = creds.get("DB_SOCKET_DIR", "/cloudsql")
    cloud_sql_connection_name = creds["CLOUD_SQL_CONNECTION_NAME"]

    pool = sqlalchemy.create_engine(
        # Equivalent URL:
        # postgres+pg8000://<db_user>:<db_pass>@/<db_name>
        #                         ?unix_sock=<socket_path>/<cloud_sql_instance_name>/.s.PGSQL.5432
        sqlalchemy.engine.url.URL.create(
            drivername="postgresql+pg8000",
            username=db_user,  # e.g. "my-database-user"
            password=db_pass,  # e.g. "my-database-password"
            database=db_name,  # e.g. "my-database-name"
            query={
                "unix_sock": f"{db_socket_dir}/{cloud_sql_connection_name}/.s.PGSQL.5432"
                # e.g. "/cloudsql", "<PROJECT-NAME>:<INSTANCE-REGION>:<INSTANCE-NAME>"
            },
        ),
        **db_config,
    )
    pool.dialect.description_encoding = None
    logger.info("Database engine initialized from unix connection")

    return pool


# [END cloudrun_user_auth_sql_connect]


def create_tables() -> None:
    """Initializes SQLAlchemy connection and creates database table."""
    # This is called before any request on the main app, ensuring the database has been setup
    logger.info("Creating tables")
    global db
    db = init_connection_engine()
    # Create pet_votes table if it doesn't already exist
    with db.begin() as conn:
        conn.execute(
            sqlalchemy.text(
                "CREATE TABLE IF NOT EXISTS pet_votes"
                "( vote_id SERIAL NOT NULL, "
                "time_cast timestamp NOT NULL, "
                "candidate VARCHAR(6) NOT NULL, "
                "uid VARCHAR(128) NOT NULL, "
                "PRIMARY KEY (vote_id)"
                ");"
            )
        )
        conn.execute(
            sqlalchemy.text(
                "CREATE TABLE IF NOT EXISTS active_users"
                "( user_id SERIAL NOT NULL, "
                "username VARCHAR(128) NOT NULL, "
                "tokens INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (user_id), "
                "UNIQUE (username)"
                ");"
            )
        )


def authenticate_user(uid: str):
    # Check if the user already exists in the active_users table
    with db.connect() as conn:
        user_exists = conn.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM active_users WHERE username=:username"
            ),
            parameters={"username": uid},
        ).scalar()

    # If the user doesn't exist, insert a new row with an initial token supply
    if not user_exists:
        try:
            with db.begin() as conn:
                conn.execute(
                    sqlalchemy.text(
                        "INSERT INTO active_users (username, tokens) VALUES (:username, :tokens)"
                    ),
                    parameters={"username": uid, "tokens": 100}  # Set an initial token supply
                )
        except IntegrityError:
            # Handle potential concurrent insertions by catching IntegrityError
            # This can happen if another process/thread inserted the same username
            # between our SELECT and INSERT queries
            pass

def get_index_context() -> dict[str, Any]:
    """Query PostgreSQL database and transform data for UI.

    Returns:
        A dictionary of counts and votes.
    """
    votes = []
    with db.connect() as conn:
        # Execute the query and fetch all results
        recent_votes = conn.execute(
            sqlalchemy.text(
                "SELECT candidate, time_cast FROM pet_votes "
                "ORDER BY time_cast DESC LIMIT 5"
            )
        ).fetchall()
        # Convert the results into a list of dicts representing votes
        for row in recent_votes:
            votes.append(
                {
                    "candidate": row[0],
                    "time_cast": row[1],
                }
            )
        stmt = sqlalchemy.text(
            "SELECT COUNT(vote_id) FROM pet_votes WHERE candidate=:candidate"
        )
        # Count number of votes for cats
        cats_count = conn.execute(stmt, parameters={"candidate": "CATS"}).scalar()
        # Count number of votes for dogs
        dogs_count = conn.execute(stmt, parameters={"candidate": "DOGS"}).scalar()
    return {
        "dogs_count": dogs_count,
        "recent_votes": votes,
        "cats_count": cats_count,
    }

def add_tokens_to_user(uid: str, amount: int) -> bool:
    """Add tokens to a user's token balance."""
    with db.begin() as conn:
        # Get the current token count for the user
        current_tokens = conn.execute(
            sqlalchemy.text(
                "SELECT tokens FROM active_users WHERE username=:username"
            ),
            parameters={"username": uid},
        ).scalar()

        if current_tokens is not None:
            # Calculate the new token count
            new_tokens = current_tokens + amount

            # Update the user's token count in the database
            conn.execute(
                sqlalchemy.text(
                    "UPDATE active_users SET tokens=:new_tokens WHERE username=:username"
                ),
                parameters={"new_tokens": new_tokens, "username": uid},
            )
        else:
            # User not found in active_users table
            raise ValueError(f"User '{uid}' not found.")

def get_tokens_for_uid(uid: str) -> int:
    """Fetch the token count for a given user."""
    with db.connect() as conn:
        result = conn.execute(
            sqlalchemy.text(
                "SELECT tokens FROM active_users WHERE username=:username"
            ),
            parameters={"username": uid},
        )
        row = result.fetchone()
        if row:
            return row[0]
        else:
            return None  # User not found in active_users table


def save_vote(team: str, uid: str, time_cast: datetime.datetime) -> None:
    """Save a vote into the PostgreSQL database.

    Args:
        team: the name of the team
        uid: the user id
        time_cast: the time of the vote
    """
    # Preparing a statement before hand can help protect against injections.
    stmt = sqlalchemy.text(
        "INSERT INTO pet_votes (time_cast, candidate, uid)"
        " VALUES (:time_cast, :candidate, :uid)"
    )

    # Using a with statement ensures that the connection is always released
    # back into the pool at the end of statement (even if an error occurs)
    with db.begin() as conn:
        conn.execute(
            stmt, parameters={"time_cast": time_cast, "candidate": team, "uid": uid}
        )
    logger.info("Vote for %s saved.", team)


def shutdown() -> None:
    """Clean up sessions and database connections."""
    # Find all Sessions in memory and close them.
    close_all_sessions()
    logger.info("All sessions closed.")
    # Each connection was released on execution, so just formally
    # dispose of the db connection if it's been instantiated
    if db:
        db.dispose()
        logger.info("Database connection disposed.")
