import io
import logging
import time
import urllib
from typing import Optional

import requests

POLL_TIME_SECONDS = 5

l = logging.getLogger("client.db")


from .perf_measure import print_runtime_stats, for_all_methods


@for_all_methods(print_runtime_stats)
class Db:

    CHANGE_TICK_TIME = "/api/v1/tick/time"
    EVENT_LIST = "/api/v1/events"
    FLAGS_FOR_TICK = "/api/v1/flags/{}"
    FLAG_SUBMISSION = "/api/v1/flag/submit/{}"
    GAME_STATE_PATH = "/api/v1/game/state"
    GENERATE_FLAG = "/api/v1/flag/generate/"
    GET_LATEST_FLAG = "/api/v1/flag/latest/{}/{}"    
    IS_GAME_STATE_PUBLIC = "/api/v1/game/is_game_state_public/{}"
    NEW_EVENT = "/api/v1/event"
    TIMESTAMPED_EVENT = "/api/v1/timestamped_event"
    NEW_TICKET = "/api/v1/ticket/{}"
    NEW_TICKET_MESSAGE = "/api/v1/ticket/{}/message"
    PATCH_INFO = "/api/v1/patch/{}"
    SERVICE_INFO = "/api/v1/service/{}"
    SERVICE_LIST = "/api/v1/services"
    SET_GAME_STATE_DELAY = "/api/v1/game/game_state_delay/{}"
    SET_PATCH_STATUS = "/api/v1/patch/{}/status"
    START_GAME = "/api/v1/game/start"
    TEAM_ALLOWED_MESSAGE = "/api/v1/ticket/{}/message/{}/team"
    TEAM_ENDPOINT = "/api/v1/team/{}"
    TEAM_FROM_IP = "/api/v1/team-from-ip/{}"
    TEAM_LIST = "/api/v1/teams"
    TEAM_PATCHES = "/api/v1/team/{}/uploaded_patches"
    TEAM_PCAP = "/api/v1/team/{}/pcaps"
    TEAM_TICKET_LIST = "/api/v1/tickets/{}"
    UPDATE_TICK_PATH = "/api/v1/tick/next"
    UPLOAD_PATCH = "/api/v1/service/upload_patch"
    VISUALIZATION = "/api/v1/visualization"

    def __init__(self, database_api="http://master.admin.31337.ooo:30000/", use_test_app=False):
        self.use_test_app = use_test_app
        l.info(f"Initializing database client for API {database_api}, are we using the test app: {use_test_app}")
        if use_test_app:
            from ..api import app, db, init_test_data
            db.create_all()
            init_test_data(reset_game=True)
            self.test_client = app.test_client()
        else:
            self.database_api = database_api

    def _get(self, game_path):
        if self.use_test_app:
            response = self.test_client.get(game_path)
        else:
            response = requests.get(self.database_api + game_path)

        if response.status_code != 200:
            l.warning(f"received a non-200 status code {response.status_code} for {game_path} {response}")
            return None

        if self.use_test_app:
            return response.json
        else:
            return response.json()

    def _post(self, game_path, data=None, files=None):
        if self.use_test_app:
            if files:
                for file_name, file_value in files.items():
                    data[file_name] = (io.BytesIO(file_value), file_name)
            response = self.test_client.post(game_path, data=data)
        else:
            response = requests.post(self.database_api + game_path, data=data, files=files)

        if self.use_test_app:
            return response.json
        else:
            return response.json()
            
    def game_state(self):
        return self._get(Db.GAME_STATE_PATH)

    def services(self):
        return self._get(Db.SERVICE_LIST)['services']

    def service(self, service_id):
        return self._get(Db.SERVICE_INFO.format(urllib.parse.quote(str(service_id))))
    
    def teams(self):
        return self._get(Db.TEAM_LIST)['teams']

    def update_event(self, **kwargs):
        return self._post(Db.NEW_EVENT, data=kwargs)

    def new_timestamped_event(self, **kwargs):
        return self._post(Db.TIMESTAMPED_EVENT, data=kwargs)

    def events(self):
        return self._get(Db.EVENT_LIST)['events']

    def generate_flag(self, service_id, team_id):
        return self._post(Db.GENERATE_FLAG + f"{service_id}/{team_id}")

    def get_flag(self, service_id, team_id):
        return self._get(Db.GET_LATEST_FLAG.format(service_id, team_id))

    def new_tick(self):
        return self._post(Db.UPDATE_TICK_PATH)

    def start_game(self):
        return self._post(Db.START_GAME)

    def change_tick_time(self, new_tick_time_seconds):
        return self._post(Db.CHANGE_TICK_TIME, data=dict(tick_time_seconds=new_tick_time_seconds))

    def team(self, team_id):
        return self._get(Db.TEAM_ENDPOINT.format(urllib.parse.quote(str(team_id))))

    def submit_flag(self, team_id, flag):
        return self._post(Db.FLAG_SUBMISSION.format(urllib.parse.quote(str(team_id))),
                          data=dict(
                              flag=flag
                          ))

    def upload_patch(self, team_id, service_id, file):
        return self._post(Db.UPLOAD_PATCH,
                          data={'service_id': service_id, 'team_id': team_id},
                          files={'uploaded_file': file})
    def patch(self, patch_id):
        return self._get(Db.PATCH_INFO.format(urllib.parse.quote(str(patch_id))))

    def set_patch_status(self, patch_id, status, public_metadata=None, private_metadata=None):
        return self._post(Db.SET_PATCH_STATUS.format(patch_id),
                          data=dict(status=status,
                                    public_metadata=public_metadata,
                                    private_metadata=private_metadata,
                          ))

    def tickets(self, team_id):
        return self._get(Db.TEAM_TICKET_LIST.format(team_id))

    def new_ticket(self, team_id, subject, description):
        return self._post(Db.NEW_TICKET.format(team_id),
                          data={'subject': subject, 'description': description})

    def new_ticket_message(self, team_id, ticket_id, message_text):
        jdata = self._get(Db.TEAM_ALLOWED_MESSAGE.format(ticket_id, team_id))
        assert jdata["message"] == "permitted"

        return self._post(Db.NEW_TICKET_MESSAGE.format(ticket_id),
                          data={'message_text': message_text, 'is_team_message': True})

    def team_pcaps(self, team_id):
        return self._get(Db.TEAM_PCAP.format(urllib.parse.quote(str(team_id))))

    def team_patches(self, team_id):
        return self._get(Db.TEAM_PATCHES.format(urllib.parse.quote(str(team_id))))

    def team_from_ip(self, ip):
        return self._get(Db.TEAM_FROM_IP.format(str(urllib.parse.quote(ip))))

    def set_is_game_state_public(self, is_public):
        return self._post(Db.IS_GAME_STATE_PUBLIC.format(1 if is_public else 0))

    def set_game_state_delay(self, delay):
        return self._post(Db.SET_GAME_STATE_DELAY.format(delay))

    def public_game_state(self):
        return self._get(Db.VISUALIZATION)

    def flags_for_tick(self, tick_id):
        return self._get(Db.FLAGS_FOR_TICK.format(str(urllib.parse.quote(tick_id))))
        
    def wait_until_new_tick(self, poll_time_seconds=POLL_TIME_SECONDS) -> Optional[int]:
        """
        poll the DB every `poll_time_seconds` seconds until there is a new tick.
        :return: the previous tick  (None for tick 1)
        """
        game_state = self.game_state()
        prev_tick = game_state['tick']
    
        l.info(f"Previous tick is {prev_tick}")
    
        done = False
        while not done:
            game_state = self.game_state()
            new_tick = game_state['tick']

            if prev_tick == new_tick:
                time.sleep(poll_time_seconds)
            else:
                done = True
        l.info(f"New tick is {new_tick}")
        return prev_tick

    def wait_until_running(self, poll_time_seconds=POLL_TIME_SECONDS):
        game_state = self.game_state()
        while game_state['state'] != 'RUNNING':
            l.info(f"Game is in {game_state['state']} state, waiting until in RUNNING state.")
            l.info(f"Going to sleep for {poll_time_seconds}.")
            time.sleep(poll_time_seconds)
            game_state = self.game_state()
        return
