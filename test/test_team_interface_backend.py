#!/usr/bin/env python3
"""
team interface backend server tests.
"""
import io
import unittest.mock

import ooogame.team_interface.backend.app as app
from ooogame.database.client import Db

TEAM_1_HEADERS = {"TEAM_ID": 1}
TEAM_2_HEADERS = {"TEAM_ID": 2}

def init_db_for_ticket_testing():
    app.db = Db("", True)
    client = app.app.test_client()
    TICKET_CREATE_MSG = "ticket created successfully"
    response = client.post("/api/ticket",
                           data=dict(subject="subject Team 1", description="description Team 1"),
                           headers=TEAM_1_HEADERS)
    assert response.status_code == 200
    assert 'message' in response.json
    assert response.json["message"] == TICKET_CREATE_MSG, f"not equal {response.json['message']} != {TICKET_CREATE_MSG}"

    return client

def test_create_ticket():
    client = init_db_for_ticket_testing()


def test_list_tickets():
    client = init_db_for_ticket_testing()
    response = client.get("/api/tickets", headers=TEAM_1_HEADERS)

    assert response.status_code == 200

    tickets = response.json["tickets"]

    for t in tickets:
        assert t["team_id"] == 1
        assert t["subject"].startswith("subject Team 1")
        assert t["description"].startswith("description Team 1")


def test_create_message():
    client = init_db_for_ticket_testing()
    ticket_msg_add_msg = f"Message for ticket #{1} added successfully"
    base_message = "Message from Team 1"

    response = client.post("/api/ticket",
                           data=dict(subject="subject Team 2", description="description Team 2"),
                           headers=TEAM_2_HEADERS)

    for x in range(0, 100):
        response = client.post("/api/ticket/1/message", data=dict(message_text=base_message + f" {x}"),
                               headers=TEAM_1_HEADERS)

        assert response.status_code == 200, f"{response.status_code}, {response.headers}"

        assert response.json["message"].startswith(ticket_msg_add_msg), \
            f"message={response.json['message']} does NOT start with {ticket_msg_add_msg}"

    response = client.get("/api/tickets", headers=TEAM_1_HEADERS)
    assert response.status_code == 200
    tickets = response.json["tickets"]

    for t in tickets:
        assert t["team_id"] == 1
        assert t["subject"].startswith("subject Team 1")
        assert t["description"].startswith("description Team 1")
        assert len(t["messages"]) == 100, f"{len(t['messages'])}"
        for m in t["messages"]:
            assert m["message_text"].startswith(base_message)


def test_team_info():
    app.db = Db("", True)
    client = app.app.test_client()
    response = client.get("/api/team_info", headers=TEAM_1_HEADERS)
    assert response.status_code == 200
    assert response.json['id'] == 1

def test_services_info():
    app.db = Db("", True)
    client = app.app.test_client()

    response = app.db.start_game()
    service = [s for s in app.db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']
    
    response = client.get("/api/services_info", headers=TEAM_1_HEADERS)
    assert len(response.json['services']) == 0

    # release service 1
    response = app.db.test_client.post(f"/api/v1/service/{service_id}/is_visible/1")

    # Activate service 1
    response = app.db.test_client.post(f"/api/v1/service/{service_id}/is_active/1")
    
    response = client.get("/api/services_info", headers=TEAM_1_HEADERS)
    assert len(response.json['services']) == 1

def test_pcap_info():
    app.db = Db("", True)
    client = app.app.test_client()

    service = [s for s in app.db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']


    response = app.db.start_game()
    
    response = client.get("/api/pcap_info", headers=TEAM_1_HEADERS)
    assert len(response.json) == 0

    # release service 3
    response = app.db.test_client.post(f"/api/v1/service/{service_id}/is_visible/1")

    # Activate service 3
    response = app.db.test_client.post(f"/api/v1/service/{service_id}/is_active/1")

    # Release pcaps for service 3
    response = app.db.test_client.post(f"/api/v1/service/{service_id}/release_pcaps/1")

    # create a pcap released event
    response = app.db.test_client.post("/api/v1/event",
                           data=dict(
                               event_type="PCAP_RELEASED",
                               reason="Test of pcap released event.",
                               service_id=service_id,
                               team_id=1,
                               pcap_name=f"team_1_service_{service_id}_1000.released.pcap",
                           ))

    assert response.status_code == 200

    response = client.get("/api/pcap_info", headers=TEAM_1_HEADERS)
    assert len(response.json) == 1
    assert response.json[0]['service_id'] == service_id
    assert 'created_on' in response.json[0]
    assert 'pcap_location' in response.json[0]


def test_flag_submission():
    app.db = Db("", True)
    client = app.app.test_client()

    response = app.db.start_game()
    
    response = client.get("/api/pcap_info", headers=TEAM_1_HEADERS)
    assert len(response.json) == 0

    # release service 3
    response = app.db.test_client.post("/api/v1/service/3/is_visible/1")

    # Activate service 3
    response = app.db.test_client.post("/api/v1/service/3/is_active/1")

    # Generate a flag for service 3 team 4
    result = app.db.generate_flag(3, 4)
    flag_id = result['id']
    flag = result['flag']

    response = client.post("/api/submit_flag/incorrect_flag", headers=TEAM_1_HEADERS)
    assert response.json['message'] == "INCORRECT"

    response = client.post(f"/api/submit_flag/{flag}", headers=TEAM_1_HEADERS)
    assert response.json['message'] == "CORRECT"


def test_submit_patches():
    app.db = Db("", True)
    client = app.app.test_client()

    service = [s for s in app.db.services() if s['type'] == 'NORMAL'][0]
    service_id = service['id']


    # Start the game!
    response = app.db.start_game()

    response = client.get("/api/patches_info", headers=TEAM_1_HEADERS)

    assert len(response.json) == 0


    # Need to activate the service first

    response = app.db.test_client.post(f"/api/v1/service/{service_id}/is_active/1")
    assert response.status_code == 200

    response = client.post("/api/submit_patch/",
                           data=dict(
                               service_id=service_id,
                               file=(io.BytesIO(b"This is a binary"), "test_binary"),
                               ),
                           headers=TEAM_1_HEADERS)
    assert response.status_code == 200
    assert 'message' in response.json
    assert response.json['message'] == "upload successful"

    response = client.get("/api/patches_info", headers=TEAM_1_HEADERS)
    assert len(response.json) == 1

    assert 'public_metadata' in response.json[0]['results'][0]
    assert not 'private_metadata' in response.json[0]['results'][0]
