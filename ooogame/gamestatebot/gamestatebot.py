#!/usr/bin/env python3
import argparse
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Optional

from ..database import Db

l = logging.getLogger("gamestatebot")


# Will upload if UPLOAD_SCOREBOARD=1
PUBLIC_SCOREBOARD_UPLOAD_KEY_PATH = os.path.expanduser('/opt/ooogame/scoreboard_upload.ppk')
PUBLIC_SCOREBOARD_UPLOAD_ARG = 'direct_webroot_d@a.scoreboard.ooo:/d/' # + filename
PUBLIC_SCOREBOARD_UPLOAD_HOSTKEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJ/aqjwk5KreSKcjcbP8wVhaN6gjcpVnZIABKHCnE8MT'  # Otherwise we'd have to pipe in 'yes' to accept the key the first time


def public_uploader_bg(local_name, remote_name, previous_upload_to_check: Optional[subprocess.Popen]) -> Optional[subprocess.Popen]:
    """Background upload, each new upload checks that the previous process completed successfully."""
    #if os.getenv("UPLOAD_SCOREBOARD") != "1":
    #    l.debug("Not uploading to the public scoreboard, set UPLOAD_SCOREBOARD=1 to enable.")
    #    return None
    assert os.path.exists(PUBLIC_SCOREBOARD_UPLOAD_KEY_PATH)
    prv = previous_upload_to_check
    if prv is not None:
        poll = prv.poll()
        if poll is None:
            l.error("Previous public upload %s (pid %d) was not finished yet! leaving it on",
                    prv, prv.pid)
        elif prv.returncode != 0:
            l.error("Previous public upload %s (pid %d) failed! exitcode %d",
                    prv, prv.pid, prv.returncode)
    cmd = ['pscp', '-sftp', '-C']  # sftp with compression
    cmd += ['-i', PUBLIC_SCOREBOARD_UPLOAD_KEY_PATH]
    cmd += ['-hostkey', PUBLIC_SCOREBOARD_UPLOAD_HOSTKEY]
    cmd += ['-q','-batch','-2']
    cmd += [local_name, PUBLIC_SCOREBOARD_UPLOAD_ARG + remote_name]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    l.info("Started public upload %s (pid %d)", p, p.pid)
    return p


def start_upload_game_state(game_state_json_path, tick: int, previous_upload_to_check: Optional[subprocess.Popen]) -> Optional[subprocess.Popen]:
    """Background upload, each new tick checks that the previous process completed successfully"""
    remote_name = f'game_state_{tick}.json'  # I think keeping the tick id simplifies a lot of things. We need the .json extension.
    return public_uploader_bg(local_name=game_state_json_path, remote_name=remote_name, previous_upload_to_check=previous_upload_to_check)




def create_game_state_dir_structure(game_state_dir):
    l.info(f"creating the game state directory based on {game_state_dir}")
    root = pathlib.Path(game_state_dir)
    assert root.exists()

    required_dirs = ['released', 'game_states']
    for r in required_dirs:
        sub_dir = root.joinpath(r)
        if not sub_dir.exists():
            l.info(f"creating {sub_dir}")
            sub_dir.mkdir(0o755)

def main(the_db, game_state_dir, max_ticks=None):
    l.info("Started up the gamestatebot")
    assert os.path.isdir(game_state_dir)
    i = 0
    scoreboard_upload_p: Optional[subprocess.Popen] = None
    while True:
        tick_id : Optional[int] = the_db.wait_until_new_tick()
        if tick_id is None:
            l.info("I think we're on the very first tick (previous_tick is None), no previous tick status to save")
            continue
        l.info(f"got a new tick, let's save the game state of the old tick {tick_id}")
        new_game_state = the_db.public_game_state()  # XXX: This is not in sync! We're already in tick_id+1 (seen in current_tick + some fast events will be there)

        new_pcap_location = pathlib.Path(f"{game_state_dir}/game_states/game_state_{tick_id}")
        l.info(f"saving public game state to {new_pcap_location}")
        with open(new_pcap_location, 'w') as f:
            json.dump(new_game_state, f)

        released = pathlib.Path(f"{game_state_dir}/released/game_state.json")

        settings = the_db.game_state()

        if settings['is_game_state_public']:
            delay = settings['game_state_delay']
            tick_to_get = tick_id - delay
            if tick_to_get <= 0:
                l.info(f"{tick_to_get} from delay {delay} is too far back, skipping")
                continue
            to_release = pathlib.Path(f"{game_state_dir}/game_states/game_state_{tick_to_get}")
            if not to_release.exists():
                l.error(f"No delayed by {delay} game state found at {to_release}")
            else:
                scoreboard_upload_p = start_upload_game_state(to_release, tick_to_get, scoreboard_upload_p)
                shutil.copyfile(to_release, released)
                l.info(f"Released file {to_release} to {released}")
        else:
            l.info("game state is not public, do not update")
            if released.exists():
                l.info(f"{released=} exists, going to delete it")
                released.unlink()

            # SPECIAL FOR THE LAST DAY ONLY: upload anyway (very little will be shown)
            l.info("Special: still uploading to the scoreboard, which filters data itself")
            scoreboard_upload_p = start_upload_game_state(new_pcap_location, tick_id, scoreboard_upload_p)

        i += 1
        if i == max_ticks:
            l.info(f"Hit the max number of ticks {max_ticks} {i}")
            return



if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="gamebot", epilog="To increase the log level: export LOG_LEVEL=DEBUG")
    parser.add_argument("--dbapi", help="The location of the database API (must provide this or $DATABASE_API)")
    parser.add_argument("--game-state-dir", required=True, help="The location of the game-state structure. Must exist. See below for creating subdirs.")
    parser.add_argument("--create-game-state-dir", action='store_true', help="Auto-create my subdirs under game-state-dir if they're not already there")
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

    game_state_dir = args.game_state_dir

    if args.create_game_state_dir:
        create_game_state_dir_structure(game_state_dir)

    the_db = Db(database_api)
    main(the_db=the_db, game_state_dir=game_state_dir)
