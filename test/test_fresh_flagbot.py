#!/usr/bin/env python3
"""
fresh-flagbot tests.
"""
import unittest.mock

import kubernetes

import ooogame.fresh_flagbot.fresh_flagbot as fresh_flagbot
import ooogame.flagbot.flagbot as flagbot
from ooogame.database.client import Db

import test_flagbot

def test_fresh_flagbot_normal():
    db = Db("", True)

    start_game = db.start_game()
    db.wait_until_new_tick = unittest.mock.Mock(return_value=True)
    assert len(db.events()) == 0

    k8s_api = test_flagbot.get_mock_k8s_service()
    flagbot.main(db, k8s_api, max_ticks=1, concurrency=False, concurrency_lib='threading')

    # now that we have flags, see if the fresh flagbot will set the flags correctly
    kubernetes.watch.Watch = unittest.mock.Mock()

    result = unittest.mock.Mock()
    result.status.phase = "Running"

    # Create the proper service name based on the current data
    service = db.services()[0]
    
    result.metadata.name = f"{service['name']}-team-1-cc957dd9b-jdb8f"
    result.status.container_statuses = [unittest.mock.Mock()]
    kubernetes.watch.Watch.return_value.stream.return_value = [{'object': result}]

    prior_events = db.events()
    fresh_flagbot.main(db, k8s_api, max_ticks=1)

    events = db.events()
    assert len(events) != len(prior_events)

def test_fresh_flagbot_private():
    db = Db("", True)

    start_game = db.start_game()
    db.wait_until_new_tick = unittest.mock.Mock(return_value=True)
    assert len(db.events()) == 0

    k8s_api = test_flagbot.get_mock_k8s_service()
    flagbot.main(db, k8s_api, max_ticks=1, concurrency=False, concurrency_lib='threading')

    # now that we have flags, see if the fresh flagbot will set the flags correctly
    kubernetes.watch.Watch = unittest.mock.Mock()

    result = unittest.mock.Mock()
    result.status.phase = "Running"

    # Create the proper service name based on the current data
    service = db.services()[0]

    result.metadata.name = f"{service['name']}-team-1-team-10-ccjk7dd9b-jdb8f"
    result.status.container_statuses = [unittest.mock.Mock()]
    kubernetes.watch.Watch.return_value.stream.return_value = [{'object': result}]

    prior_events = db.events()
    fresh_flagbot.main(db, k8s_api, max_ticks=1)

    events = db.events()
    assert len(events) != len(prior_events)
