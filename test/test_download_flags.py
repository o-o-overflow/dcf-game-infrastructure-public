#!/usr/bin/env python3
"""
flagbot tests.
"""

import os

from pyfakefs.fake_filesystem_unittest import Patcher

import ooogame.download_flags.download_flags as download_flags
import ooogame.flagbot.flagbot as flagbot

from ooogame.database.client import Db

import test_flagbot

def test_download_flags():
    db = Db("", True)

    service = [s for s in db.services() if s['type'] == 'NORMAL'][0]

    start_game = db.start_game()

    k8s_api = test_flagbot.get_mock_k8s_service()
    flagbot.main(db, k8s_api, max_ticks=1, wait=False, concurrency=False, concurrency_lib='threading')
    with Patcher() as patcher:
        download_flags.download_flags(db, service['id'], 1, "flags")
        teams = db.teams()
        for t in teams:
            assert os.path.exists(f"./flags/1/{t['id']}.flag")
    
