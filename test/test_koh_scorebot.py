#!/usr/bin/env python3
"""
fresh-flagbot tests.
"""
import unittest.mock

import kubernetes

import ooogame
import ooogame.koh_scorebot.koh_scorebot as koh_scorebot
import ooogame.flagbot.flagbot as flagbot
from ooogame.database.client import Db

import test_flagbot

def test_get_koh_score_from_pod():
    k8s_api = test_flagbot.get_mock_k8s_service()
    kubernetes.stream.stream.return_value = "result_from_pod"
    result = koh_scorebot.get_koh_score_from_pod("pod_name", "pod_namespace", "/score", k8s_api)
    assert result == "result_from_pod"

    kubernetes.stream.stream.side_effect = Exception('Test')
    result = koh_scorebot.get_koh_score_from_pod("pod_name", "pod_namespace", "/score", k8s_api)
    assert result == None
    kubernetes.stream.stream.side_effect = None

def test_get_score_with_central():
    test_services = [{'id': 1, 'name': 'test-1', 'type': 'KING_OF_THE_HILL', 'central_server': '', 'score_location': '/score'},
                     {'id': 2, 'name': 'testing-koh-private', 'type': 'KING_OF_THE_HILL', 'central_server': 'central-server-k8s-pod', 'score_location': '/foo/bar/test'},
                     {'id': 2, 'name': 'testing-central', 'type': 'NORMAL', 'central_server': 'central-k8s-pod', 'flag_location': '/var/rhg/flags/', 'isolation': "SHARED"},
                     {'id': 3, 'name': 'testing-private', 'type': 'NORMAL', 'central_server': '', 'flag_location': '/flag', 'isolation': "PRIVATE"}]

    with unittest.mock.patch("ooogame.database.client.Db.services", unittest.mock.Mock(return_value=test_services)):
        db = Db("", True)
        db.change_tick_time(1)
        start_game = db.start_game()

        # mock out the wait_until_new_tick so that we don't hang
        db.wait_until_new_tick = unittest.mock.Mock(return_value=True)

        assert len(db.events()) == 0

        k8s_api = test_flagbot.get_mock_k8s_service()
        koh_scorebot.main(db, k8s_api, max_ticks=1)

        # check that the events were created
        events = db.events()
        assert len(events) != 0

        for event in events:
            assert event['event_type'] == 'KOH_RANKING' or event['event_type'] == 'KOH_SCORE_FETCH'


def test_get_score():
    k8s_api = test_flagbot.get_mock_k8s_service()
    db = Db("", True)
    start_game = db.start_game()

    teams = db.teams()
    koh_services = list(s for s in db.services() if s['type'] == "KING_OF_THE_HILL")

    team = teams[0]
    koh_service = koh_services[0]

    db.wait_until_new_tick = unittest.mock.Mock(return_value=1)
    koh_scorebot.get_koh_score_from_pod = unittest.mock.Mock(return_value="10\nfoobar")
    score, metadata = koh_scorebot.get_score(team, koh_service, "/score", k8s_api, db)

    assert score == 10
    assert metadata == "foobar"

    koh_scorebot.get_koh_score_from_pod = unittest.mock.Mock(return_value="100")
    score, metadata = koh_scorebot.get_score(team, koh_service, "/score", k8s_api, db)
    assert score == 100
    assert metadata == None

    koh_scorebot.get_koh_score_from_pod = unittest.mock.Mock(return_value="jfkldjakfdjafdasjfdlsakjfdklsajfdslk")
    score, metadata = koh_scorebot.get_score(team, koh_service, "/score", k8s_api, db)
    assert score == 0
    assert metadata == None

    koh_scorebot.get_koh_score_from_pod = unittest.mock.Mock(return_value="100000000000000000000000000000000000000000000000000000000000000000000000")
    score, metadata = koh_scorebot.get_score(team, koh_service, "/score", k8s_api, db)
    assert score == ooogame.koh_scorebot.koh_scorebot.MAX_KOH_SCORE
    assert metadata == None

    k8s_api.list_pod_for_all_namespaces.side_effect = Exception('Test')
    score, metadata = koh_scorebot.get_score(team, koh_service, "/score", k8s_api, db)
    assert score == 0
    assert metadata == None
    k8s_api.list_pod_for_all_namespaces.side_effect = None

def test_koh_scorebot():
    k8s_api = test_flagbot.get_mock_k8s_service()
    db = Db("", True)
    start_game = db.start_game()

    teams = db.teams()
    koh_services = list(s for s in db.services() if s['type'] == "KING_OF_THE_HILL")

    team = teams[0]
    koh_service = koh_services[0]

    db.wait_until_new_tick = unittest.mock.Mock(return_value=1)

    koh_scorebot.main(db, k8s_api, 1)
