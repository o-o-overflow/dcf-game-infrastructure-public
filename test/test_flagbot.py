#!/usr/bin/env python3
"""
flagbot tests.
"""
import unittest.mock

import kubernetes

import ooogame.flagbot.flagbot as flagbot
from ooogame.database.client import Db

def get_mock_k8s_service():
    k8s_api = unittest.mock.Mock()
    k8s_api.list_pod_for_all_namespaces = unittest.mock.Mock()
    pod_return = unittest.mock.Mock()
    pod_return.metadata.deletion_timestamp = None
    pod_return.status.phase = 'Running'

    k8s_api.list_pod_for_all_namespaces.return_value.items = [pod_return]

    kubernetes.stream.stream = unittest.mock.Mock()

    return k8s_api

def test_set_flag_pod():
    k8s_api = get_mock_k8s_service()
    result = flagbot.set_flag_pod("testing", "/flag", "pod-name", "namespace", k8s_api)

    assert result == flagbot.FlagResult.SUCCESS
    kubernetes.stream.stream.assert_called_once()
    kubernetes.stream.stream.return_value.write_stdin.assert_called_once()

def test_set_flag_deployment():
    k8s_api = get_mock_k8s_service()

    result = flagbot.set_flag_deployment("testing", "k8s-deployment-name", "/flag", {"id": 1, "name": "team-name"}, {'id': 1}, k8s_api)

    assert result == flagbot.FlagResult.SUCCESS

    k8s_api.list_pod_for_all_namespaces.assert_called_once()
    kubernetes.stream.stream.assert_called_once()
    kubernetes.stream.stream.return_value.write_stdin.assert_called_once()

def test_flagbot():
    db = Db("", True)
    db.change_tick_time(1)
    start_game = db.start_game()

    # mock out the wait_until_new_tick so that we don't hang
    db.wait_until_new_tick = unittest.mock.Mock(return_value=True)

    assert len(db.events()) == 0

    k8s_api = get_mock_k8s_service()
    flagbot.main(db, k8s_api, max_ticks=1, concurrency=False, concurrency_lib='threading')

    # check that the events were created
    events = db.events()
    assert len(events) != 0

    for event in events:
        assert event['event_type'] == 'SET_FLAG'
        assert event['result'] == 'SUCCESS'

def test_flagbot_with_central_and_private():
    test_services = [{'id': 1, 'name': 'test-1', 'type': 'KING_OF_THE_HILL', 'is_active': '1'},
                     {'id': 2, 'name': 'testing-central', 'type': 'NORMAL', 'central_server': 'central-k8s-pod', 'flag_location': '/var/rhg/flags/', 'isolation': "SHARED", 'is_active': '1'},
                     {'id': 3, 'name': 'testing-private', 'type': 'NORMAL', 'central_server': '', 'flag_location': '/flag', 'isolation': "PRIVATE", 'is_active': '1'}]
    with unittest.mock.patch("ooogame.database.client.Db.services", unittest.mock.Mock(return_value=test_services)):
        db = Db("", True)
        db.change_tick_time(1)
        start_game = db.start_game()

        # mock out the wait_until_new_tick so that we don't hang
        db.wait_until_new_tick = unittest.mock.Mock(return_value=True)

        assert len(db.events()) == 0

        k8s_api = get_mock_k8s_service()
        flagbot.main(db, k8s_api, max_ticks=1, concurrency=False, concurrency_lib='threading')

        # check that the events were created
        events = db.events()
        assert len(events) != 0

        for event in events:
            assert event['event_type'] == 'SET_FLAG'
            assert event['result'] == 'SUCCESS'
