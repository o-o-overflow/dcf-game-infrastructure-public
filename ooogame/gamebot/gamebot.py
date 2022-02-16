#!/usr/bin/env python3
import argparse
import logging
import os
import sys
import time

from ..database import Db

l = logging.getLogger("gamebot")

def main(the_db, max_ticks=None):

    l.info("Just started up.")
    i = 0
    while True:        
        the_db.wait_until_running()
        game_state = the_db.game_state()
        estimated_tick_time_remaining = game_state['estimated_tick_time_remaining']

        l.info(f"Going to sleep for {estimated_tick_time_remaining} seconds.")
        time.sleep(estimated_tick_time_remaining)

        l.info("Back up, let's do our thing.")
        l.info("Going to update the tick.")
        the_db.new_tick()
        i += 1
        if i == max_ticks:
            l.info(f"Hit the max number of ticks {max_ticks} {i}")
            return

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="gamebot")
    parser.add_argument("--dbapi", help="The location of the database API")
    parser.add_argument("--version", action="version", version="%(prog)s v1.0.0")
    
    args = parser.parse_args()

    database_api = None
    if args.dbapi:
        database_api = args.dbapi
    elif 'DATABASE_API' in os.environ:
        database_api = os.environ['DATABASE_API']

    if not database_api:
        l.error("Error, must specify a database api")
        parser.print_help()
        sys.exit(1)

    the_db = Db(database_api)
    main(the_db=the_db)
