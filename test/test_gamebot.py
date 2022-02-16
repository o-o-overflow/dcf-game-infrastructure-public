#!/usr/bin/env python3
"""
gamebot tests
"""

import ooogame.gamebot.gamebot as gamebot

from ooogame.database.client import Db

def test_gamebot():
    db = Db("", True)

    db.change_tick_time(1)
    start_game = db.start_game()
    start_tick = start_game['tick']

    gamebot.main(db, max_ticks=1)
    state = db.game_state()

    assert int(state['tick']) == (int(start_tick) + 1)

    start_tick = state['tick']
    
    gamebot.main(db, max_ticks=2)

    new_state = db.game_state()
    assert int(new_state['tick']) == (int(start_tick) + 2)
