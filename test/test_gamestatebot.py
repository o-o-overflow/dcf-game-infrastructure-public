#!/usr/bin/env python3
"""
gamestate tests
"""
import io
import os
import socket
import unittest.mock

from pyfakefs.fake_filesystem_unittest import Patcher

import ooogame.gamestatebot.gamestatebot as gamestatebot
from ooogame.database.client import Db

def test_create_game_state_dir_structure():
    db = Db("", True)

    start_game = db.start_game()

    with Patcher() as patcher:
        patcher.fs.create_dir("/game_state")
        gamestatebot.create_game_state_dir_structure("/game_state")

        assert os.path.exists('/game_state/game_states')
        assert os.path.exists('/game_state/released')

def test_gamestatebot():
    db = Db("", True)

    start_game = db.start_game()
    db.wait_until_new_tick = unittest.mock.Mock(return_value=1)

    with Patcher() as patcher:
        patcher.fs.create_dir("/game_state")
        patcher.fs.create_dir("/game_state/game_states")
        patcher.fs.create_dir("/game_state/released")

        # mock out the uploading function
        gamestatebot.start_upload_game_state = unittest.mock.Mock(return_value=True)
        gamestatebot.main(db, "/game_state", max_ticks=1)

        assert os.path.exists('/game_state/game_states/game_state_1')
        assert not os.path.exists('/game_state/released/game_state.json')

        db.set_is_game_state_public(True)
        db.set_game_state_delay(0)
        db.wait_until_new_tick = unittest.mock.Mock(return_value=2)

        gamestatebot.main(db, "/game_state", max_ticks=1)

        assert os.path.exists('/game_state/game_states/game_state_2')
        assert os.path.exists('/game_state/released/game_state.json')

        assert open('/game_state/game_states/game_state_2', 'r').read() == open('/game_state/released/game_state.json', 'r').read()

        test_content = "test_test_test"
        patcher.fs.create_file('/game_state/game_states/game_state_9', contents=test_content)
        db.set_game_state_delay(1)

        db.wait_until_new_tick = unittest.mock.Mock(return_value=10)

        gamestatebot.main(db, "/game_state", max_ticks=1)

        assert os.path.exists('/game_state/game_states/game_state_10')
        assert open('/game_state/released/game_state.json', 'r').read() == test_content

        # something weird happens, we missed some game_states, what happens?
        db.wait_until_new_tick = unittest.mock.Mock(return_value=100)
        gamestatebot.main(db, "/game_state", max_ticks=1)
        assert os.path.exists('/game_state/game_states/game_state_100')
