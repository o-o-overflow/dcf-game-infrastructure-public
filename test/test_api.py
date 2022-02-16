#!/usr/bin/env python3
"""
API server tests.
"""
import io
import os
import json
import uuid
import yaml
import time
import base64
import hashlib
import random
import datetime
import dateutil.parser
import unittest.mock

import ooogame.database.api as app

DEFAULT_TICKET_STATUS = "OPEN"
TICKET_CREATE_MSG = "ticket created successfully"
TEST_TEAM_ID = 1
TEST_TICKET_ID = 1
MAX_TEST_TEAM=10

def test_create_ticket():

    test_subject = f"SUBJECT {TEST_TEAM_ID} {random.randint(0, 0xFFFFFFFF)}"
    test_description = f"DESCRIPTION {TEST_TEAM_ID} {random.randint(0, 0xFFFFFFFF)}"

    client = init_for_ticket_testing(test_subject, test_description)

    response = client.post(f"/api/v1/ticket/{TEST_TEAM_ID}",data=dict(subject=test_subject, description=test_description))

    assert response.status_code == 200, f"status code ==> {response.status_code}"
    assert response.json["message"] == TICKET_CREATE_MSG, f"not equal {response.json['message']} != {TICKET_CREATE_MSG}"

    response = client.get("/api/v1/tickets")

    print(f"response={response.status_code}, json={response.json}  ")

    assert response.status_code == 200, f"status code ==> {response.status_code}"
    assert "tickets" in response.json, f"tickets not in response.json ==> {response.json}"
    tickets = response.json["tickets"]
    assert len(tickets) > 0, "No Tickets returned from query"
    t = tickets[0]
    eval_ticket(t, TEST_TEAM_ID, test_subject, test_description, DEFAULT_TICKET_STATUS)


def test_list_team_tickets():
    client = init_for_ticket_testing()

    tickets_opened_by_test_team = 0
    number_tickets_to_create = 100

    # find all prior tickets created by test team, to set starting count
    response = client.get("/api/v1/tickets")
    tickets = response.json["tickets"]
    for t in tickets:
        if t["team_id"] == TEST_TEAM_ID:
            tickets_opened_by_test_team += 1
    pre_created_tickets = len(tickets)

    for cnt in range(0, number_tickets_to_create-pre_created_tickets):
        random_team_id = random.randint(1, MAX_TEST_TEAM) if tickets_opened_by_test_team > 0 else TEST_TEAM_ID
        if random_team_id == TEST_TEAM_ID:
            tickets_opened_by_test_team += 1
        test_subject = f"SUBJECT {random_team_id} {random.randint(0, 0xFFFFFFFF)}"
        test_description = f"DESCRIPTION {random_team_id} {random.randint(0, 0xFFFFFFFF)}"

        response = client.post(f"/api/v1/ticket/{random_team_id}",data=dict(subject=test_subject,
                                                                            description=test_description))
        assert response.status_code == 200, f"status code ==> {response.status_code}"
        assert response.json["message"] == TICKET_CREATE_MSG, f"not equal {response.json['message']} != {TICKET_CREATE_MSG}"

    # Did all the tickets get created?
    response = client.get("/api/v1/tickets")
    assert response.status_code == 200, f"status code ==> {response.status_code}"
    tickets = response.json["tickets"]
    assert len(tickets) == number_tickets_to_create, f"Tickets returned not equal, {len(tickets)} != {number_tickets_to_create}"
    assert tickets_opened_by_test_team > 0, "Failed to create any tickets for test team"

    print(f"Created {number_tickets_to_create} TICKETS ")

    # Does it filter by team and only return the teams ?
    response = client.get(f"/api/v1/tickets/{TEST_TEAM_ID}")
    assert response.status_code == 200, f"status code ==> {response.status_code}"
    assert "tickets" in response.json
    tickets = response.json["tickets"]

    assert len(tickets) == tickets_opened_by_test_team, \
        f"Tickets returned not equal, {len(tickets)} != {tickets_opened_by_test_team}"

    for t in tickets:
        eval_ticket(t, TEST_TEAM_ID, f"SUBJECT {TEST_TEAM_ID}", f"DESCRIPTION {TEST_TEAM_ID}", "OPEN")

def test_add_ticket_fail():
    client = init_for_ticket_testing()
    response = client.post(f"/api/v1/ticket/{TEST_TEAM_ID}", data=dict(description="desc w/o subject"))
    assert response.status_code == 500

    response = client.post(f"/api/v1/ticket/{TEST_TEAM_ID}", data=dict(subject="subject w/o desc"))
    assert response.status_code == 500


def test_ticket_team_check():
    client = init_for_ticket_testing()

    response = client.get(f"/api/v1/ticket/1/message/{TEST_TEAM_ID}/team")
    assert response.status_code == 200
    assert response.json["message"] == "permitted"

    response = client.get(f"/api/v1/ticket/1/message/5/team")
    assert response.status_code == 200
    assert response.json["message"] == "unauthorized attempt to add a message"


def test_add_status_fail():
    client = init_for_ticket_testing()

    # RI test, ticket does not exist
    response = client.post(f"/api/v1/ticket/status/1999393", data=dict(status="OPEN"))
    assert response.status_code == 500, f"status code ==> {response.status_code}"

    # RI test, status does not exist
    response = client.post(f"/api/v1/ticket/status/{TEST_TEAM_ID}", data=dict(status="IMNOTREAL"))
    assert response.status_code == 500, f"status code ==> {response.status_code}"


def test_add_ticket_status():

    client = init_for_ticket_testing()
    ticket_status_add_msg = "status updated for ticket"

    client.post(f"/api/v1/ticket/{TEST_TEAM_ID}", data=dict(subject="subject herez", description="desc"))

    def verify_ticket_status(client, test_status):
        response = client.post(f"/api/v1/ticket/status/{TEST_TICKET_ID}", data=dict(status=test_status))
        assert response.status_code == 200, f"status code ==> {response.status_code}"
        assert response.json["message"].startswith(ticket_status_add_msg), \
            f"message={response.json['message']} does NOT start with {ticket_status_add_msg}"

        response = client.get("/api/v1/tickets")
        tickets = response.json["tickets"]
        for t in tickets:
            if t["id"] == TEST_TICKET_ID:
                assert t["status"] == test_status
                return

    verify_ticket_status(client, test_status="CLOSED")
    verify_ticket_status(client, test_status="OPEN")
    verify_ticket_status(client, test_status="CLOSED")
    verify_ticket_status(client, test_status="CLOSED")
    verify_ticket_status(client, test_status="OPEN")


def test_add_admin_message():
    client = init_for_ticket_testing()

    test_message_text = f"MESSAGE_TEXT ADMIN {random.randint(0, 0xFFFFFFFF)}"
    ticket_msg_add_msg = f"Message for ticket #{TEST_TICKET_ID} added successfully"

    response = client.post(f"/api/v1/ticket/{TEST_TICKET_ID}/message", data=dict(message_text=test_message_text))
    verify_message(response, ticket_msg_add_msg)

    response = client.get("/api/v1/tickets")
    ticket = response.json['tickets'][0]

    for msg in ticket['messages']:
        if not msg['is_team_message']:
            assert msg['message_text'] == test_message_text
            break


def test_add_team_message():
    client = init_for_ticket_testing()

    test_message_text = f"MESSAGE_TEXT TEAM {TEST_TEAM_ID} {random.randint(0, 0xFFFFFFFF)}"
    ticket_msg_add_msg = f"Message for ticket #{TEST_TICKET_ID} added successfully"

    response = client.post(f"/api/v1/ticket/{TEST_TICKET_ID}/message", data=dict(message_text=test_message_text,
                                                                                 is_team_message=True))
    verify_message(response, ticket_msg_add_msg)

    response = client.get("/api/v1/tickets")
    ticket = response.json['tickets'][0]

    for msg in ticket['messages']:
        if msg['is_team_message']:
            assert msg['message_text'] == test_message_text
            break

# ---------------~~~~~~~~~~~<[ utililty functions for ticket testing ]>~~~~~~~~~~~~~~~~~------------------

def verify_message(response, test_message):
    assert response.status_code == 200, f"status code ==> {response.status_code}"

    assert response.json["message"].startswith(test_message), \
        f"message={response.json['message']} does NOT start with {test_message}"


def init_for_ticket_testing(subject=f"SUBJECT {TEST_TEAM_ID}", description=f"DESCRIPTION {TEST_TEAM_ID}"):
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get(f"/api/v1/tickets")
    if len(response.json["tickets"]) == 0:
        client.post(f"/api/v1/ticket/{TEST_TEAM_ID}", data=dict(subject=subject, description=description))

    return client


def eval_ticket(t, test_team_id, test_subject, test_desc, test_status):
    assert t["team_id"] == test_team_id, f"not equal {t['team_id']} != {test_team_id}"
    assert t["subject"].startswith(test_subject), f"t['subject']={t['subject']} does not start with {test_subject}"
    assert t["description"].startswith(test_desc), f"t['description']={t['description']} does not start with {test_desc}"
    assert t["status"] == test_status, f"not equal {t['status']} != {test_status}"


# ---------------~~~~~~~~~~~<[   END UTILITY FUNCTION AREA 51   ]>~~~~~~~~~~~~~~~~~------------------

def test_teams():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    response = client.get("/api/v1/teams")
    assert response.status_code == 200
    assert "teams" in response.json
    assert isinstance(response.json["teams"], list)
    assert "id" in response.json["teams"][0]
    assert "name" in response.json["teams"][0]
    assert "team_network" in response.json["teams"][0]

    assert len(app.db.session.query(app.Deleted).all()) == 0

    team_id = response.json["teams"][0]["id"]
    team = app.db.session.query(app.Team).get(team_id)
    app.db.session.delete(team)
    app.db.session.commit()

    response = client.get("/api/v1/teams")
    assert response.status_code == 200

    assert team_id != response.json["teams"][0]["id"]

    assert len(app.db.session.query(app.Deleted).all()) == 1
    deleted = app.db.session.query(app.Deleted).all()[0]

    assert str(team_id).encode() in deleted.content


def test_team_info():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    response = client.get("/api/v1/team/1")
    assert response.status_code == 200
    assert "id" in response.json
    assert "name" in response.json
    assert "team_network" in response.json


def _get_normal_service(client):
    response = client.get("/api/v1/services")
    assert response.status_code == 200

    services = response.json['services']
    to_return = None
    for s in services:
        if s['type'] == "NORMAL":
            to_return = s
            break
    assert to_return != None
    return to_return

def _get_different_normal_service(client, service):
    response = client.get("/api/v1/services")
    assert response.status_code == 200

    services = response.json['services']
    to_return = None
    for s in services:
        if s['id'] == service['id']:
            continue
        if s['type'] == "NORMAL":
            to_return = s
            break
    assert to_return != None
    return to_return


def test_flag_creation_and_submission():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    service = _get_normal_service(client)
    service_id = service['id']

    # Check without the game running, it should not create a flag
    response = client.post(f"/api/v1/flag/generate/{service_id}/1")
    assert response.status_code != 200

    # Start the game!
    response = client.post("/api/v1/game/start")
    assert response.status_code == 200

    response = client.post(f"/api/v1/flag/generate/{service_id}/1")

    assert "id" in response.json
    assert "flag" in response.json
    flag_tick_id = response.json['tick_id']
    flag_id = response.json['id']

    assert len(response.json["flag"]) > 5

    the_flag = response.json["flag"]

    # Test that if we generate a flag for the same tick, we will get the same flag
    new_response = client.post(f"/api/v1/flag/generate/{service_id}/1")
    assert flag_tick_id == new_response.json['tick_id']
    assert flag_id == new_response.json['id']

    # Test if we can get this flag from the "latest" endpoint
    response = client.get(f"/api/v1/flag/latest/{service_id}/1")
    assert response.status_code == 200

    assert response.json['flag'] == the_flag

    # Test if flags for ticks returns this
    response = client.get(f"/api/v1/flags/{flag_tick_id}")
    assert len(response.json) == 1

    assert response.json[0]['flag'] == the_flag

    # service is not active, so flags don't count

    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'SERVICE_INACTIVE'

    response = client.post(f"/api/v1/service/{service_id}/is_active/1")
    assert response.status_code == 200

    # service is now active, so the flag should count

    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    # check that the event made it
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 1, response.json
    event = response.json['events'][0]
    assert 'id' in event
    assert 'FLAG_STOLEN' == event['event_type']
    assert 'reason' in event
    assert flag_tick_id == event['tick_id']
    assert 2 == event['exploit_team_id']
    assert 1 == event['victim_team_id']
    assert service_id == event['service_id']
    assert flag_id == event['flag_id']

    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.json['result'] == 'ALREADY_SUBMITTED'

    fake_flag = "OOOwillthisonedo"
    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=fake_flag
                           ))
    assert response.json['result'] == 'INCORRECT'

    # Test team1 submitting own flag
    response = client.post("/api/v1/flag/submit/1",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.json['result'] == 'OWN_FLAG'

    # Test team2 submitting a super old flag
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']

    response = client.post(f"/api/v1/flag/generate/{service_id}/1")
    the_flag = response.json["flag"]

    for i in range(app.NUM_TICKS_FLAG_VALID_FOR + 1):
        response = client.post("/api/v1/tick/next")
        new_tick = response.json['tick']

    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.json['result'] == 'TOO_OLD', response.json

    # Test team2 submitting an almost old flag
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']

    response = client.post(f"/api/v1/flag/generate/{service_id}/1")
    the_flag = response.json["flag"]

    flag_id = response.json["id"]

    for i in range(app.NUM_TICKS_FLAG_VALID_FOR):
        response = client.post("/api/v1/tick/next")
        new_tick = response.json['tick']

    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.json['result'] == 'CORRECT', response.json

    # test deleting a flag

    response = client.post(f"/api/v1/flag/generate/{service_id}/1")
    flag_id = response.json["id"]

    the_flag = app.db.session.query(app.Flag).get(flag_id)
    app.db.session.delete(the_flag)
    app.db.session.commit()

    assert len(app.db.session.query(app.Deleted).all()) != 1
    deleted = app.db.session.query(app.Deleted).all()[-1]

    assert str(flag_id).encode() in deleted.content



def test_game_state():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/game/state")
    assert response.status_code == 200
    assert response.json['state'] == 'INIT'
    assert 'tick' in response.json
    assert 'current_tick_created_on' in response.json

    # Test changing game state

    for state in ["RUNNING", "PAUSED", "STOPPED", "INIT"]:
        response = client.post("/api/v1/game/state",
                               data=dict(
                                   state=state
                               ))
        assert response.status_code == 200

        response = client.get("/api/v1/game/state")
        assert response.json['state'] == state

    # test invalid staring the game
    response = client.post("/api/v1/game/state",
                           data=dict(
                               state="RUNNING"
                           ))
    assert response.status_code == 200
    response = client.post("/api/v1/game/start")
    assert response.status_code != 200

    # test staring the game
    response = client.post("/api/v1/game/state",
                           data=dict(
                               state="INIT"
                           ))
    assert response.status_code == 200
    response = client.post("/api/v1/game/start")

    first_tick = response.json['tick']

    # ensure that game is now running and the tick is returned
    response = client.get("/api/v1/game/state")
    assert response.json['state'] == "RUNNING"
    assert response.json['tick'] == first_tick
    assert response.json['current_tick_created_on'] != None

    # now tick that tock!
    response = client.post("/api/v1/tick/next")
    assert response.json['tick'] != first_tick
    new_tick = response.json['tick']

    response = client.get("/api/v1/game/state")
    assert response.json['tick'] == new_tick


def _test_service_one(service):
    yml_service_data = yaml.safe_load(open(os.path.join(os.path.dirname(os.path.realpath(app.__file__)), 'service_info.yml'), 'r'))[
        'services']
    assert len(yml_service_data) > 0, f"service_info.yml has no services\n\tyml_service_data={yml_service_data}"
    srv1 = yml_service_data[0]
    assert srv1['type'].lower() == "normal", "1st service in yaml should be 'normal' for tests to work correctly."
    assert 'limit_memory' in srv1 and 'request_memory' in srv1, "1st service in yaml should explicitly set memory limits for tests to work correctly"
    assert service['flag_location'] == srv1['flag_location']
    assert service['description'] == srv1['description']
    assert service['central_server'] == srv1['central_server']
    assert service['isolation'] == srv1['isolation']

    assert service['port'] == srv1['port']
    assert service['container_port'] == srv1['container_port']
    assert 'description' in service
    assert 'max_bytes' in service, service
    assert 'patchable_file_from_service_dir' in service
    assert 'patchable_file_from_docker' in service
    assert service['interaction_docker']
    assert service['local_interaction_docker']
    assert service['service_docker']
    assert service['release_pcaps'] == False
    assert service['is_visible'] == False
    assert service['is_active'] == False
    assert service['service_indicator'] == "GOOD"
    assert 'local_interaction_scripts' in service

    assert len(service['exploit_scripts']) == len(srv1['exploit_scripts']), \
        f"{len(service['exploit_scripts'])} NOT= {len(srv1['exploit_scripts'])}"

    assert len(service['sla_scripts']) == len(srv1['sla_scripts'])
    assert srv1['sla_scripts'][0] in service['sla_scripts']

    assert srv1['limit_memory'] == service['limit_memory']
    assert srv1['request_memory'] == service['request_memory']


def _test_koh_service(service):
    assert service['score_location'] == '/home/reverse/conf/score.dat'
    assert service['port'] == 7777
    assert 'description' in service
    assert service['type'] == "KING_OF_THE_HILL"
    assert service['repo_url'] == "git@github.com:o-o-overflow/finals-chall-reverse.git"


def test_service_list():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/services")
    assert response.status_code == 200

    services = response.json['services']


def test_service():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    service = _get_normal_service(client)

    response = client.get(f"/api/v1/service/{service['id']}")
    _test_service_one(response.json)


def test_toggle_service_functions():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    service = _get_normal_service(client)
    service_id = service['id']

    for prop in ["release_pcaps", "is_visible", "is_active"]:
        response = client.post(f"/api/v1/service/{service_id}/{prop}/1")
        assert response.status_code == 200

        response = client.get(f"/api/v1/service/{service_id}")
        assert response.json[prop] == True

        response = client.post(f"/api/v1/service/{service_id}/{prop}/0")
        assert response.status_code == 200

        response = client.get(f"/api/v1/service/{service_id}")
        assert response.json[prop] == False


def test_tick_length():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/game/state")

    assert response.json['tick_time_seconds'] == app.TickTime._DEFAULT_TICK_TIME
    assert response.json['is_game_state_public'] == app.IsGameStatePublic._DEFAULT_VALUE

    assert 'estimated_tick_time_remaining' in response.json

    assert response.json['estimated_tick_time_remaining'] >= 0

    prev_time = response.json['estimated_tick_time_remaining']

    response = client.get("/api/v1/game/state")

    assert prev_time > response.json['estimated_tick_time_remaining']

    response = client.post("/api/v1/tick/time",
                           data=dict(
                               tick_time_seconds=10,
                           ))
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['tick_time_seconds'] == 10

    response = client.post("/api/v1/tick/time",
                           data=dict(
                               tick_time_seconds=500,
                           ))
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['tick_time_seconds'] == 500


def test_is_game_state_public():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/game/state")
    assert response.json['is_game_state_public'] == app.IsGameStatePublic._DEFAULT_VALUE

    response = client.post("/api/v1/game/is_game_state_public/1")
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['is_game_state_public'] == True

    response = client.post("/api/v1/game/is_game_state_public/0")
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['is_game_state_public'] == False


def test_game_state_delay():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/game/state")
    assert response.json['game_state_delay'] == app.GameStateDelay._DEFAULT_VALUE

    response = client.post("/api/v1/game/game_state_delay/10")
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['game_state_delay'] == 10

    response = client.post("/api/v1/game/game_state_delay/0")
    assert response.status_code == 200

    response = client.get("/api/v1/game/state")
    assert response.json['game_state_delay'] == 0


def test_ip_to_team():
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    response = client.get("/api/v1/team-from-ip/10.1.0.20")
    assert response.status_code == 200
    assert response.json['team_id'] == 1

    response = client.get("/api/v1/team-from-ip/192.168.10.12")
    assert response.json['team_id'] == None


def test_events():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    # Start the game
    response = client.post("/api/v1/game/start")

    # check that the endpoints exist
    for endpoint in ["/api/v1/events", "/api/v1/events/1"]:
        response = client.get(endpoint)
        assert response.status_code == 200
        assert 'events' in response.json

    # Create a new event
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=2,
                               service_id=1,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))

    assert response.status_code == 200, response

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 1, response.json
    event = response.json['events'][0]
    assert event['event_type'] == 'EXPLOIT_SCRIPT'
    assert event['team_id'] == 2
    assert event['service_id'] == 1
    assert event['ip'] == '127.0.0.1'
    assert event['port'] == 31337
    assert event['service_interaction_docker'] == 'testing-interaction'
    assert event['the_script'] == '/exploit.sh'
    assert 'docker_registry' in event
    assert event['result'] == "SUCCESS"

    # Try SLA Script

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="SLA_SCRIPT",
                               reason="Testing the application.",
                               team_id=2,
                               service_id=1,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))

    assert response.status_code == 200, response

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 2
    event = response.json['events'][1]
    assert event['event_type'] == 'SLA_SCRIPT'
    assert event['team_id'] == 2
    assert event['service_id'] == 1
    assert 'tick_id' in event
    assert event['ip'] == '127.0.0.1'
    assert event['port'] == 31337
    assert event['service_interaction_docker'] == 'testing-interaction'
    assert event['the_script'] == '/exploit.sh'
    assert 'docker_registry' in event
    assert event['result'] == "SUCCESS"

    # Test set flag event
    # Need to get a flag
    response = client.post("/api/v1/flag/generate/2/1")
    assert response.status_code == 200

    flag_id = response.json['id']
    the_flag = response.json['flag']

    # Test if we can get this flag from the "latest" endpoint
    response = client.get("/api/v1/flag/latest/2/1")
    assert response.status_code == 200

    assert response.json['flag'] == the_flag

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="SET_FLAG",
                               reason="Testing the application.",
                               team_id=1,
                               service_id=2,
                               flag_id=flag_id,
                               result="SUCCESS",
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 3
    event = response.json['events'][2]
    assert event['event_type'] == 'SET_FLAG'
    assert event['team_id'] == 1
    assert event['service_id'] == 2
    assert event['flag_id'] == flag_id
    assert event['result'] == "SUCCESS"

    # Test KoH Events
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_SCORE_FETCH",
                               reason="Successly extracted score.",
                               team_id=1,
                               service_id=3,
                               score=10,
                               data="foobar",
                               result="SUCCESS",
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 4
    event = response.json['events'][3]
    assert event['event_type'] == 'KOH_SCORE_FETCH'
    assert event['team_id'] == 1
    assert event['service_id'] == 3
    assert event['score'] == 10
    assert event['data'] == "foobar"
    assert event['result'] == "SUCCESS"

    # Failed score fetching event
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_SCORE_FETCH",
                               reason="Failed to extract score.",
                               team_id=2,
                               service_id=3,
                               result="FAIL",
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 5
    event = response.json['events'][4]
    assert event['event_type'] == 'KOH_SCORE_FETCH'
    assert event['team_id'] == 2
    assert event['service_id'] == 3
    assert event['result'] == "FAIL"

    # posting a koh ranking event, which is a bit complicated

    # first, get all teams to generate a fake ranking

    response = client.get("/api/v1/teams")
    teams = response.json['teams']
    max_score = len(teams) + 1

    ranking = []
    rank = 1
    score = max_score
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=score,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        score -= 1
        rank += 1

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason="Ranking of teams for service 3 tick 2.",
                               tick_id=2,
                               ranking=json.dumps(ranking),
                               service_id=3,
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 6
    event = response.json['events'][5]
    assert event['event_type'] == 'KOH_RANKING'
    assert event['service_id'] == 3
    assert event['tick_id'] == 2

    assert len(event['ranking']) == len(ranking)

    # Test the pcap created event

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="PCAP_CREATED",
                               reason="Test of pcap creation event.",
                               service_id=1,
                               team_id=2,
                               pcap_name="team_2_service_1_1000.pcap",
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 7
    event = response.json['events'][6]
    assert event['event_type'] == 'PCAP_CREATED'
    assert event['service_id'] == 1
    assert event['team_id'] == 2

    # Test the pcap released event

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="PCAP_RELEASED",
                               reason="Test of pcap released event.",
                               service_id=1,
                               team_id=2,
                               pcap_name="team_2_service_1_1000.released.pcap",
                           ))

    assert response.status_code == 200

    # check that it's in all events
    response = client.get("/api/v1/events")
    assert len(response.json['events']) == 8
    event = response.json['events'][7]
    assert event['event_type'] == 'PCAP_RELEASED'
    assert event['service_id'] == 1
    assert event['team_id'] == 2


def test_defense():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    service = _get_normal_service(client)
    service_id = service['id']

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    # first get the number of teams
    response = client.get("/api/v1/teams")
    teams = response.json['teams']

    response = client.get("/api/v1/services")
    services = response.json['services']

    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    response = client.get("/api/v1/score/{}".format(new_tick))
    assert response.status_code == 200

    assert response.json['tick_id'] == new_tick

    assert len(teams) == len(response.json['teams'])

    # there's been no flags submitted yet, so all the team's attack scores should be 0, defense should be num(services where type == normal), and koh should be 0
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['ATTACK'] == 0
        assert team_score['DEFENSE'] == 0
        assert team_score['KING_OF_THE_HILL'] == 0

    # Activate service 1
    response = client.post(f"/api/v1/service/{service_id}/is_active/1")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']

    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    response = client.post(f"/api/v1/flag/generate/{service_id}/2")

    assert "id" in response.json
    assert "flag" in response.json
    flag_tick_id = response.json['tick_id']
    flag_id = response.json['id']
    the_flag = response.json['flag']

    response = client.post("/api/v1/flag/submit/1",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    # Team 1 should have an attack score of 1
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1:
            assert team_score['ATTACK'] == 1
        else:
            assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == 1
        assert team_score['KING_OF_THE_HILL'] == 0

    # Active another normal service
    other_service = _get_different_normal_service(client, service)
    other_service_id = other_service['id']

    response = client.post(f"/api/v1/service/{other_service_id}/is_active/1")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']
    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    response = client.post(f"/api/v1/flag/generate/{other_service_id}/2")

    assert "id" in response.json
    assert "flag" in response.json
    flag_tick_id = response.json['tick_id']
    flag_id = response.json['id']
    the_flag = response.json['flag']

    response = client.post("/api/v1/flag/submit/1",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    # Team 1 should have an attack score of 1
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1:
            assert team_score['ATTACK'] == 2
        else:
            assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == num_normal_services, f"team_score['DEFENSE']={team_score['DEFENSE']}"
        assert team_score['KING_OF_THE_HILL'] == 0


def test_scores():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    # first get the number of teams
    response = client.get("/api/v1/teams")
    teams = response.json['teams']

    response = client.get("/api/v1/services")
    services = response.json['services']

    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    normal_services = []
    koh_services = []
    for srv in services:
        if srv['type'].lower() == "normal":
            normal_services.append(srv['id'])
        elif srv['type'].lower() == "king_of_the_hill":
            koh_services.append(srv['id'])

    response = client.get("/api/v1/score/{}".format(new_tick))
    assert response.status_code == 200

    assert response.json['tick_id'] == new_tick

    assert len(teams) == len(response.json['teams'])

    # there's been no flags submitted yet, so all the team's attack scores should be 0, defense should be num(services where type == normal), and koh should be 0
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['ATTACK'] == 0
        assert team_score['DEFENSE'] == 0
        assert team_score['KING_OF_THE_HILL'] == 0

    # When the service is not active, this should not count in the score

    # Run our exploit against team 2, service should go down
    # Create a new event
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=2,
                               service_id=1,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))
    assert response.status_code == 200, response

    # Check that team 2's points did not go down
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['ATTACK'] == 0
        assert team_score['DEFENSE'] == 0
        assert team_score['KING_OF_THE_HILL'] == 0

    # Activate service 1

    response = client.post(f"/api/v1/service/{normal_services[0]}/is_active/1")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']
    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    # Run our exploit against team 2, service should go down
    # Create a new event
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=2,
                               service_id=1,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))
    assert response.status_code == 200, response

    # Check that team 2's points went down
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == 0
        assert team_score['KING_OF_THE_HILL'] == 0

    # Failed exploit script shouldn't change scores
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=1,
                               service_id=1,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="FAIL",
                           ))
    assert response.status_code == 200, response

    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == 0
        assert team_score['KING_OF_THE_HILL'] == 0

    # Active service 3

    print(f"starting ofr {normal_services[1]}")

    response = client.post(f"/api/v1/service/{normal_services[1]}/is_active/1")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']
    num_normal_services = len([s for s in services if s['type'] == "NORMAL" and s['is_active']])

    response = client.post(f"/api/v1/flag/generate/{normal_services[1]}/2")

    assert "id" in response.json
    assert "flag" in response.json
    flag_tick_id = response.json['tick_id']
    flag_id = response.json['id']
    the_flag = response.json['flag']

    # Test if we can get this flag from the "latest" endpoint
    response = client.get(f"/api/v1/flag/latest/{normal_services[1]}/2")
    assert response.status_code == 200
    assert response.json['flag'] == the_flag

    response = client.post("/api/v1/flag/submit/1",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    # Team 1 should have an attack score of 1
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1:
            assert team_score['ATTACK'] == 1
        else:
            assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == 1, f"team_score ={team_score}"
        assert team_score['KING_OF_THE_HILL'] == 0

    # if we exploit a service that is not active, should have no effect

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=3,
                               service_id=4,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))
    assert response.status_code == 200, response

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="EXPLOIT_SCRIPT",
                               reason="Testing the application.",
                               team_id=4,
                               service_id=4,
                               ip="127.0.0.1",
                               port=31337,
                               service_interaction_docker="testing-interaction",
                               the_script="/exploit.sh",
                               docker_registry="",
                               result="SUCCESS",
                           ))
    assert response.status_code == 200, response

    # Team 1 should have an attack score of 1
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1:
            assert team_score['ATTACK'] == 1
        else:
            assert team_score['ATTACK'] == 0
        if t['id'] == 2:
            assert team_score['DEFENSE'] == 0
        else:
            assert team_score['DEFENSE'] == 1
        assert team_score['KING_OF_THE_HILL'] == 0

    response = client.get("/api/v1/scores")
    assert response.status_code == 200
    assert len(response.json) == 1

    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']
    response = client.get("/api/v1/scores")
    assert response.status_code == 200
    assert len(response.json) == 2

    # Time to test the KoH Scoring

    response = client.get("/api/v1/teams")
    teams = response.json['teams']
    max_score = len(teams) + 1

    ranking = []
    rank = 1
    score = max_score
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=score,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        score -= 1
        rank += 1

    ranking.sort(key=lambda result: (result['score']), reverse=True)

    # Need to activate KoH service
    koh_id = koh_services[0]
    response = client.post(f"/api/v1/service/{koh_id}/is_active/1")
    assert response.status_code == 200

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason="Ranking of teams for service 3 tick 2.",
                               tick_id=new_tick,
                               ranking=json.dumps(ranking),
                               service_id=koh_id,
                           ))

    assert response.status_code == 200

    response = client.get("/api/v1/score/{}".format(new_tick))
    # check the KoH scores
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]

        if t['id'] == ranking[0]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 10, response.json
        elif t['id'] == ranking[1]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 6
        elif t['id'] == ranking[2]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 3
        elif t['id'] == ranking[3]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 2
        elif t['id'] == ranking[4]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 1
        else:
            assert team_score['KING_OF_THE_HILL'] == 0

    # test if first team has koh points and rest have zero
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']
    response = client.get("/api/v1/scores")

    ranking = []
    rank = 1
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=0,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        rank += 1

    ranking.sort(key=lambda result: (result['rank']))
    ranking[0]['score'] = 100

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason=f"Ranking of teams for service {koh_id} tick 2.",
                               tick_id=new_tick,
                               ranking=json.dumps(ranking),
                               service_id=koh_id,
                           ))

    assert response.status_code == 200

    response = client.get("/api/v1/score/{}".format(new_tick))

    # check the KoH scores
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]

        if t['id'] == ranking[0]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 10, response.json
        else:
            assert team_score['KING_OF_THE_HILL'] == 0

    # test if everyone has some koh points
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']
    response = client.get("/api/v1/scores")

    ranking = []
    rank = 1
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=10,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        rank += 1

    ranking.sort(key=lambda result: (result['rank']))

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason=f"Ranking of teams for service {koh_id} tick 2.",
                               tick_id=new_tick,
                               ranking=json.dumps(ranking),
                               service_id=koh_id,
                           ))

    assert response.status_code == 200

    response = client.get("/api/v1/score/{}".format(new_tick))

    # check the KoH scores
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        assert team_score['KING_OF_THE_HILL'] == 10, response.json

    # test if third place has multiple teams
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']
    response = client.get("/api/v1/scores")

    ranking = []
    rank = 1
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=10,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        rank += 1

    ranking.sort(key=lambda result: (result['rank']))
    ranking[0]['score'] = 100
    ranking[1]['score'] = 90
    ranking[2]['score'] = 80
    ranking[3]['score'] = 80
    ranking[4]['score'] = 80
    ranking[5]['score'] = 70

    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason=f"Ranking of teams for service {koh_id} tick 2.",
                               tick_id=new_tick,
                               ranking=json.dumps(ranking),
                               service_id=koh_id,
                           ))

    assert response.status_code == 200

    response = client.get("/api/v1/score/{}".format(new_tick))

    # check the KoH scores
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]

        if t['id'] == ranking[0]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 10
        elif t['id'] == ranking[1]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 6
        elif t['id'] == ranking[2]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 3
        elif t['id'] == ranking[3]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 3
        elif t['id'] == ranking[4]['team_id']:
            assert team_score['KING_OF_THE_HILL'] == 3
        else:
            assert team_score['KING_OF_THE_HILL'] == 0

    # Can we have more than one KOH at a time?
    if len(koh_services) > 1:
        koh_id_2 = koh_services[1]
        response = client.post(f"/api/v1/service/{koh_id_2}/is_active/1")
        assert response.status_code == 200

        ranking = []
        rank = 1
        score = max_score
        for t in teams:
            this_team_score = dict(rank=rank,
                                   score=score,
                                   data="some metadata {}".format(rank),
                                   team_id=t['id']
                                   )
            ranking.append(this_team_score)
            score -= 1
            rank += 1

        response = client.post("/api/v1/tick/next")
        new_tick = response.json['tick']

        for id in [koh_id, koh_id_2]:
            response = client.post("/api/v1/event",
                                   data=dict(
                                       event_type="KOH_RANKING",
                                       reason=f"Ranking of teams for KOH service {id}.",
                                       tick_id=new_tick,
                                       ranking=json.dumps(ranking),
                                       service_id=id,
                                   ))

            assert response.status_code == 200

        response = client.get("/api/v1/score/{}".format(new_tick))
        # check the KoH scores
        for t in teams:
            assert str(t['id']) in response.json['teams']
            team_score = response.json['teams'][str(t['id'])]

            if t['id'] == ranking[0]['team_id']:
                assert team_score['KING_OF_THE_HILL'] == 20, response.json
            elif t['id'] == ranking[1]['team_id']:
                assert team_score['KING_OF_THE_HILL'] == 12
            elif t['id'] == ranking[2]['team_id']:
                assert team_score['KING_OF_THE_HILL'] == 6
            elif t['id'] == ranking[3]['team_id']:
                assert team_score['KING_OF_THE_HILL'] == 4
            elif t['id'] == ranking[4]['team_id']:
                assert team_score['KING_OF_THE_HILL'] == 2
            else:
                assert team_score['KING_OF_THE_HILL'] == 0

    # let's test stealth impact on scoring
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']
    service_id = normal_services[1]

    # score a few flags
    emulated_pwns = [ (1,n) for n in range(2,17) ] + [ (2,1), (3,1), (2,4) ]
    for attacker, defender in emulated_pwns:
        response = client.post(f"/api/v1/flag/generate/{service_id}/{defender}")
        assert response.status_code == 200
        the_flag = response.json['flag']
        response = client.post(f"/api/v1/flag/submit/{attacker}", data=dict( flag=the_flag))
        assert response.status_code == 200
        assert response.json['result'] == 'CORRECT'

    # make sure the scores are right, pre-stealth
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1: assert team_score['ATTACK'] == 15
        elif t['id'] == 2: assert team_score['ATTACK'] == 2
        elif t['id'] == 3: assert team_score['ATTACK'] == 1
        else: assert team_score['ATTACK'] == 0

    # now test what happens with stealth from 1->2
    response = client.post("/api/v1/event", data=dict(
        event_type="STEALTH",
        reason="Testing stealth from team 1 to team 2",
        tick_id=new_tick,
        src_team_id=1,
        dst_team_id=2,
        service_id=service_id
    ))
    assert response.status_code == 200

    # team 1's score should have dropped by 0.5 points, but others should be the same
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1: assert team_score['ATTACK'] == 14.5
        elif t['id'] == 2: assert team_score['ATTACK'] == 2
        elif t['id'] == 3: assert team_score['ATTACK'] == 1
        else: assert team_score['ATTACK'] == 0

    # have team 1 go full stealth
    for i in range(3, 17):
        response = client.post("/api/v1/event", data=dict(
            event_type="STEALTH",
            reason=f"Testing stealth from team 1 to team {i}",
            tick_id=new_tick,
            src_team_id=1,
            dst_team_id=i,
            service_id=service_id
        ))
        assert response.status_code == 200

    # team 1 should have half points
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1: assert team_score['ATTACK'] == 7.5
        elif t['id'] == 2: assert team_score['ATTACK'] == 2
        elif t['id'] == 3: assert team_score['ATTACK'] == 1
        else: assert team_score['ATTACK'] == 0

    # make sure team 2 recipricating works properly
    response = client.post("/api/v1/event", data=dict(
        event_type="STEALTH",
        reason="Testing stealth from team 2 to team 1",
        tick_id=new_tick,
        src_team_id=2,
        dst_team_id=1,
        service_id=service_id
    ))
    assert response.status_code == 200

    # team 1's score should have dropped by 0.5 points, but others should be the same
    response = client.get("/api/v1/score/{}".format(new_tick))
    for t in teams:
        assert str(t['id']) in response.json['teams']
        team_score = response.json['teams'][str(t['id'])]
        if t['id'] == 1: assert team_score['ATTACK'] == 7.5
        elif t['id'] == 2: assert team_score['ATTACK'] == 1.5
        elif t['id'] == 3: assert team_score['ATTACK'] == 1
        else: assert team_score['ATTACK'] == 0

def test_ctftime():
    #set up services

    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    # first get the number of teams
    response = client.get("/api/v1/teams")
    teams = response.json['teams']

    response = client.get("/api/v1/services")
    services = response.json['services']

    normal_services = []
    koh_services = []
    for srv in services:
        if srv['type'].lower() == "normal":
            normal_services.append(srv['id'])
        elif srv['type'].lower() == "king_of_the_hill":
            koh_services.append(srv['id'])

    # Activate service 1
    response = client.post(f"/api/v1/service/{normal_services[0]}/is_active/1")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']

    # adjust scoreboard for teams 3, 2 in the lead
    response = client.post(f"/api/v1/flag/generate/{normal_services[0]}/13")
    the_flag = response.json['flag']
    response = client.post("/api/v1/flag/submit/3",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    response = client.post(f"/api/v1/flag/generate/{normal_services[0]}/14")
    the_flag = response.json['flag']
    response = client.post("/api/v1/flag/submit/3",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    response = client.post(f"/api/v1/flag/generate/{normal_services[0]}/15")
    the_flag = response.json['flag']
    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    #test that output file is created for ctftime call
    response = client.get("/api/v1/ctftime")
    assert os.path.exists("ctftime_scores.json") == True

    ctftime_standings = {}
    with open("ctftime_scores.json") as fp:
        ctftime_standings = json.load(fp)

    assert len(ctftime_standings) != 0
    assert len(ctftime_standings['standings']) == len(teams)

    #test team rankings are correctly sorted
    response = client.get("/api/v1/team/3")
    assert 3 == response.json['id']
    team_3_name = response.json['name']


    response = client.get("/api/v1/team/2")
    assert 2 == response.json['id']
    team_2_name = response.json['name']

    standings = ctftime_standings['standings']
    first_place = standings[0]
    assert first_place['pos'] == 1
    assert first_place['team'] == team_3_name
    assert first_place['score'] == 3

    second_place = standings[1]
    assert second_place['pos'] == 2
    assert second_place['team'] == team_2_name
    assert second_place['score'] == 2

    #test rankings are correctly updated over multiple ticks
    response = client.post("/api/v1/tick/next")

    # Activate service 3
    response = client.post(f"/api/v1/service/{normal_services[1]}/is_active/1")
    assert response.status_code == 200

    # adjust scoreboard to place team 2 in the lead
    response = client.post(f"/api/v1/flag/generate/{normal_services[0]}/9")
    the_flag = response.json['flag']
    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    response = client.post(f"/api/v1/flag/generate/{normal_services[0]}/8")
    the_flag = response.json['flag']
    response = client.post("/api/v1/flag/submit/2",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    #test that rankings are updated and correctly sorted
    response = client.get("/api/v1/ctftime")
    assert os.path.exists("ctftime_scores.json") == True

    ctftime_standings = {}
    with open("ctftime_scores.json") as fp:
        ctftime_standings = json.load(fp)

    assert len(ctftime_standings) != 0
    assert len(ctftime_standings['standings']) == len(teams)
    os.unlink("ctftime_scores.json")

    #test team rankings are correctly sorted
    standings = ctftime_standings['standings']
    first_place = standings[0]
    assert first_place['pos'] == 1
    assert first_place['team'] == team_2_name
    assert first_place['score'] == 5

    second_place = standings[1]
    assert second_place['pos'] == 2
    assert second_place['team'] == team_3_name
    assert second_place['score'] == 4


def test_uploaded_patches():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    service = _get_normal_service(client)
    service_id = service['id']


    response = client.post("/api/v1/game/start")
    assert response.status_code == 200

    response = client.get("/api/v1/services")
    services = response.json['services']
    normal_services = []
    koh_services = []
    for srv in services:
        if srv['type'].lower() == "normal":
            normal_services.append(srv['id'])
        elif srv['type'].lower() == "king_of_the_hill":
            koh_services.append(srv['id'])

    # test getting patch status of non-existent patch
    response = client.get("/api/v1/patch/1")
    assert response.status_code != 200

    # Cannt upload to a non-active service!

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=service_id,
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                           ))
    assert response.status_code == 400

    response = client.post(f"/api/v1/service/{normal_services[0]}/is_active/1")
    assert response.status_code == 200

    response = client.post(f"/api/v1/service/{koh_services[0]}/is_active/1")
    assert response.status_code == 200

    # cannot upload to KoH
    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=koh_services[0],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                           ))
    assert response.status_code == 400, f"sc={response.status_code}"

    # invalid service ID check
    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=-1,
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                           ))
    assert response.status_code == 400

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.get("/api/v1/team/10/uploaded_patches")
    assert response.status_code == 200
    assert len(response.json['patches']) == 1, response.json

    patch = response.json['patches'][0]

    response = client.get(f"/api/v1/patch/{patch['id']}")
    assert response.status_code == 200
    assert response.json['id'] == patch['id']
    assert response.json['team_id'] == patch['team_id']
    assert response.json['service_id'] == patch['service_id']
    assert response.json['uploaded_hash'] == patch['uploaded_hash']
    assert response.json['results'] == patch['results']


    m = hashlib.sha256()
    m.update(b"This is a binary")
    file_hash = m.hexdigest()

    assert patch['id'] == 1
    assert patch['team_id'] == 10
    assert patch['service_id'] == normal_services[0]
    assert patch['uploaded_hash'] == file_hash
    assert len(patch['results']) == 1
    assert patch['results'][0]['status'] == "SUBMITTED"

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is another binary"), "another_test_binary"),
                           ))
    assert response.status_code == 200

    response = client.get("/api/v1/team/10/uploaded_patches")
    assert response.status_code == 200
    assert len(response.json['patches']) == 1, response.json

    response = client.post("/api/v1/tick/next")
    assert response.status_code == 200

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is another another binary"), "another_test_binary"),
                           ))
    assert response.status_code == 200

    response = client.get("/api/v1/team/10/uploaded_patches")
    assert response.status_code == 200
    assert len(response.json['patches']) == 2, response.json

    response = client.post("/api/v1/patch/1/status",
                           data=dict(
                               status="ACCEPTED"
                           ))
    assert response.status_code == 200

    response = client.get("/api/v1/patch/1")
    assert response.status_code == 200
    assert len(response.json['results']) == 2
    assert response.json['results'][0]['status'] == "ACCEPTED"
    assert response.json['results'][0]['private_metadata'] == None
    assert response.json['results'][0]['public_metadata'] == None

def test_pcaplist():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    response = client.get("/api/v1/services")
    services = response.json['services']

    response = client.get("/api/v1/team/1/pcaps")
    assert response.status_code == 200

    assert len(response.json) == 0

    # create a pcap released event
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="PCAP_RELEASED",
                               reason="Test of pcap released event.",
                               service_id=3,
                               team_id=1,
                               pcap_name="team_1_service_3_1000.released.pcap",
                           ))

    assert response.status_code == 200

    # test that the event shows up
    response = client.get("/api/v1/team/1/pcaps")
    assert response.status_code == 200

    assert len(response.json) == 1
    assert response.json[0]['team_id'] == 1
    assert response.json[0]['service_id'] == 3
    assert response.json[0]['pcap_name'] == "team_1_service_3_1000.released.pcap"


def test_service_indicator():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    service = _get_normal_service(client)
    service_id = service['id']

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    for status in app.ServiceStatus:
        response = client.post(f"/api/v1/service/{service_id}/service_indicator/{status.name}")
        assert response.status_code == 200
        service = client.get(f"/api/v1/service/{service_id}").json
        assert service['service_indicator'] == status.name


def test_visualization():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()
    service = _get_normal_service(client)
    service_id = service['id']

    response = client.get("/api/v1/visualization")
    assert response.status_code == 200
    assert 'scores' in response.json
    assert len(response.json['scores']) == 0

    assert 'services' in response.json
    assert len(response.json['services']) == 0

    assert 'teams' in response.json
    assert len(response.json['teams']) != 0

    assert 'exploitation_events' in response.json
    assert len(response.json['exploitation_events']) == 0

    assert 'koh_rankings' in response.json
    assert len(response.json['koh_rankings']) == 0

    assert len(response.json['ticks']) == 0

    # scores, services, and teams all come from the other tested
    # interfaces, so I'm only going to test exploitation_events and koh_rankings

    # Start the game
    response = client.post("/api/v1/game/start")
    new_tick = response.json['tick']

    response = client.get("/api/v1/services")
    services = response.json['services']
    normal_services = []
    koh_services = []
    for srv in services:
        if srv['type'].lower() == "normal":
            normal_services.append(srv['id'])
        elif srv['type'].lower() == "king_of_the_hill":
            koh_services.append(srv['id'])

    # release first service
    response = client.post(f"/api/v1/service/{service_id}/is_visible/1")

    # Activate first service
    response = client.post(f"/api/v1/service/{service_id}/is_active/1")

    # generate flag for service 1 team 2
    response = client.post(f"/api/v1/flag/generate/{service_id}/2")
    assert response.status_code == 200

    the_flag = response.json['flag']

    response = client.post("/api/v1/flag/submit/1",
                           data=dict(
                               flag=the_flag
                           ))
    assert response.status_code == 200
    assert response.json['result'] == 'CORRECT'

    response = client.get("/api/v1/visualization")
    assert response.status_code == 200

    assert len(response.json['ticks']) == 1

    assert len(response.json['exploitation_events']) == 1

    new_event = response.json['exploitation_events'][0]
    assert new_event['victim_team_id'] == 2
    assert new_event['service_id'] == service_id
    assert new_event['exploit_team_id'] == 1
    assert new_event['tick'] == new_tick

    # test the KoH rankings
    response = client.post("/api/v1/tick/next")
    new_tick = response.json['tick']

    koh_service_id = koh_services[0]
    # release service 2 (koh service)
    response = client.post(f"/api/v1/service/{koh_service_id}/is_visible/1")

    # Activate service 2
    response = client.post(f"/api/v1/service/{koh_service_id}/is_active/1")

    response = client.get("/api/v1/teams")
    teams = response.json['teams']
    max_score = len(teams) + 1

    ranking = []
    rank = 1
    score = max_score
    for t in teams:
        this_team_score = dict(rank=rank,
                               score=score,
                               data="some metadata {}".format(rank),
                               team_id=t['id']
                               )
        ranking.append(this_team_score)
        score -= 1
        rank += 1

    ranking.sort(key=lambda result: (result['score']), reverse=True)
    response = client.post("/api/v1/event",
                           data=dict(
                               event_type="KOH_RANKING",
                               reason="Ranking of teams for service 2 tick 2.",
                               tick_id=new_tick,
                               ranking=json.dumps(ranking),
                               service_id=koh_service_id,
                           ))

    assert response.status_code == 200

    response = client.get("/api/v1/visualization")
    assert response.status_code == 200

    assert len(response.json['koh_rankings']) == 1

    new_event = response.json['koh_rankings'][0]
    assert new_event['service_id'] == koh_service_id, new_event
    assert new_event['tick'] == new_tick
    assert len(new_event['results']) == len(teams)

    #test patch submissions/acceptance is calculated

    # release first service
    response = client.post(f"/api/v1/service/{normal_services[0]}/is_visible/1")
    # Activate first service
    response = client.post(f"/api/v1/service/{normal_services[0]}/is_active/1")
    # release second service
    response = client.post(f"/api/v1/service/{normal_services[1]}/is_visible/1")
    # Activate second service
    response = client.post(f"/api/v1/service/{normal_services[1]}/is_active/1")

    #populate submitted patches from different teams (3,2 for service 1,2)
    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=9,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[0],
                               team_id=8,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[1],
                               team_id=8,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.post("/api/v1/service/upload_patch",
                           data=dict(
                               service_id=normal_services[1],
                               team_id=10,
                               uploaded_file=(io.BytesIO(b"This is a binary"), "test_binary"),
                       ))
    assert response.status_code == 200

    response = client.get("/api/v1/visualization")
    assert response.status_code == 200


    services = response.json['services']
    assert len(services) == 3
    service_1 = [s for s in services if s['id'] == normal_services[0]][0]
    service_2 = [s for s in services if s['id'] == normal_services[1]][0]

    assert service_1['id'] == normal_services[0]
    assert service_1['num_accepted_patches'] == 0
    assert service_1['num_submitted_patches'] == 3
    assert service_1['tick_id'] == 2

    assert service_2['id'] == normal_services[1]
    assert service_2['num_accepted_patches'] == 0
    assert service_2['num_submitted_patches'] == 2
    assert service_2['tick_id'] == 2

    #change some of the patches to accepted
    response = client.post("/api/v1/patch/1/status",
                           data=dict(
                               status="ACCEPTED"
                           ))
    assert response.status_code == 200

    response = client.post("/api/v1/patch/4/status",
                           data=dict(
                               status="ACCEPTED"
                           ))
    assert response.status_code == 200


    response = client.get("/api/v1/visualization")
    assert response.status_code == 200

    #check number of services is correct
    services = response.json['services']
    assert len(services) == 3
    service_1 = [s for s in services if s['id'] == normal_services[0]][0]
    service_2 = [s for s in services if s['id'] == normal_services[1]][0]

    assert service_1['num_accepted_patches'] == 1
    assert service_1['num_submitted_patches'] == 3
    assert service_1['tick_id'] == 2

    assert service_2['num_accepted_patches'] == 1
    assert service_2['num_submitted_patches'] == 2
    assert service_2['tick_id'] == 2





def test_tick_at():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    ticks = [ ]

    # Start the game!
    response = client.post("/api/v1/game/start")
    assert response.status_code == 200
    ticks.append(app.Tick.get_current_tick().to_json())

    for _ in range(2):
        time.sleep(5)
        response = client.post("/api/v1/tick/next")
        assert response.status_code == 200
        ticks.append(app.Tick.get_current_tick().to_json())

    for tick in ticks:
        assert app.Tick.get_tick_at(tick['created_on']).id == tick['id']
        assert app.Tick.get_tick_at(tick['created_on']+datetime.timedelta(0,1)).id == tick['id']

def test_stealth_events():
    app.db.drop_all()
    app.db.create_all()
    app.init_test_data()
    client = app.app.test_client()

    ticks = [ ]

    # Start the game!
    response = client.post("/api/v1/game/start")
    assert response.status_code == 200
    ticks.append(app.Tick.get_current_tick().to_json())

    # make some ticks
    for _ in range(2):
        time.sleep(5)
        response = client.post("/api/v1/tick/next")
        assert response.status_code == 200
        ticks.append(app.Tick.get_current_tick().to_json())

    # add some events
    for tick in ticks:
        response = client.post("/api/v1/timestamped_event", data=dict(
                event_type="STEALTH",
                reason="Testing the application.",
                service_id=tick['id'],
                src_team_id=2,
                dst_team_id=3,
                timestamp=tick['created_on'].timestamp(),
        ))
        assert response.status_code == 200

        response = client.post("/api/v1/timestamped_event", data=dict(
                event_type="STEALTH",
                reason="Testing the application.",
                service_id=tick['id'],
                src_team_id=3,
                dst_team_id=4,
                timestamp=(tick['created_on'] + datetime.timedelta(0,1)).timestamp()
        ))
        assert response.status_code == 200

    # verify
    for tick in ticks:
        events = response = client.get(f"/api/v1/events/{tick['id']}")
        assert response.status_code == 200
        assert len(response.json['events']) == 2
        assert response.json['events'][0]['service_id'] == tick['id']
        assert response.json['events'][1]['service_id'] == tick['id']
        assert response.json['events'][0]['src_team_id'] == 2
        assert response.json['events'][0]['dst_team_id'] == 3
        assert response.json['events'][1]['src_team_id'] == 3
        assert response.json['events'][1]['dst_team_id'] == 4
