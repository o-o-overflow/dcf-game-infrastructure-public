#!/usr/bin/env python3
import argparse
import logging
import os
import sys

from ..database import Db

l = logging.getLogger("download_flags")

def download_flags(the_db, service_id, tick_id, download_dir):
    flags = the_db.flags_for_tick(str(tick_id))

    if not os.path.exists(download_dir):
        l.info(f"{download_dir} does not exist, making")
        os.mkdir(download_dir)
    
    tick_dir = os.path.join(download_dir, str(tick_id))
    l.info(f"this tick dir {tick_dir}")

    if not os.path.exists(tick_dir):
        l.info(f"{tick_dir} does not exist, making")
        os.mkdir(tick_dir)

    for f in flags:
        if str(f['service_id']) == str(service_id):
            file_name = f"{f['team_id']}.flag"
            path = os.path.join(tick_dir, file_name)
            l.info(f"dropping {path}")
            with open(path, 'w') as flag_file:
                flag_file.write(f['flag'])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="flagbot")
    parser.add_argument("--dbapi", default="http://master.admin.31337.ooo:30000", help="The location of the database API")
    parser.add_argument("--version", action="version", version="%(prog)s v0.0.1")
    parser.add_argument("service_id", help="The service id to grab flags from.")    
    parser.add_argument("tick_id", help="The tick id to grab flags from.")
    parser.add_argument("download_dir", default='flags', nargs='?')

    args = parser.parse_args()

    database_api = None
    if args.dbapi:
        database_api = args.dbapi
    elif 'DATABASE_API' in os.environ:
        database_api = os.environ['DATABASE_API']

    the_db = Db(database_api)

    download_flags(the_db, args.service_id, args.tick_id, args.download_dir)

    

