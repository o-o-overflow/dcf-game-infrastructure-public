#!/usr/bin/env python3

"""
Database API.
"""
import argparse
import datetime
import enum
import ipaddress
import logging
import os
import random
import uuid
import base64
import hashlib
from functools import wraps

import yaml
from flask import Flask, jsonify, request, json
from flask_migrate import Migrate
from flask_restful import Api, Resource, abort, reqparse
from flask_rq2 import RQ
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy
from sqlalchemy import CHAR, BLOB, TypeDecorator, or_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import with_polymorphic
from werkzeug.middleware.profiler import ProfilerMiddleware

from . import Config
from ..common import PatchStatus
from ..patchbot import patchbot

l = logging.getLogger("database-api")

app = Flask(__name__)
app.config.from_object(Config())
rq = RQ(app)
# noinspection PyTypeChecker
api = Api(app)

# At this point it's easier to assert than to change the entire API
# (See the many now().isoformat()+"Z" and what not)
assert datetime.datetime.utcfromtimestamp(100000) == datetime.datetime.fromtimestamp(100000), \
    "Local time is not UTC. This is hardcoded in the db api, so please change it"

if "SQLALCHEMY_DATABASE_URI" not in os.environ:
    os.environ["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ["SQLALCHEMY_DATABASE_URI"]
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# From our discussion.
# TODO: Put this in config
NUM_TICKS_FLAG_VALID_FOR = 3


def is_tick_old_enough_to_cache(tick_id):
    """
    Is this tick old enough to cache?
    """

    current_tick_id = Tick.get_current_tick_id()
    return tick_id + NUM_TICKS_FLAG_VALID_FOR < current_tick_id


##########################################################################
####                    Get your tickets here                         ####
##########################################################################

### Ticket Actions

class NewTicket(Resource):
    """
    Create a new ticket.
    """

    def post(self, team_id: int):
        # form will have subject and descrption in them
        ticket_args = request.form.to_dict()
        ticket_args['team_id'] = team_id

        ticket = Ticket(**ticket_args)
        db.session.add(ticket)
        db.session.flush()
        ticketstatus = TicketStatus.create_default_status(ticket.id)
        db.session.add(ticketstatus)

        db.session.commit()

        team_name = json.dumps(Team.get_team_name(team_id))
        l.info(f"NEW TICKET: ticket_id={ticket.id} team_id={team_id} team_name={team_name}")

        return jsonify(message='ticket created successfully')


class NewTicketStatus(Resource):
    """
    Create a new status for this ticket
    """

    def post(self, ticket_id: int):
        # should have subject and descrption
        tstat_args = request.form.to_dict()

        assert TicketStatusTypes.is_valid(tstat_args['status'])
        # check that ticket exists in db
        TicketStatus.get_current_status(ticket_id)

        tstat_args['ticket_id'] = ticket_id
        tstat = TicketStatus(**tstat_args)
        db.session.add(tstat)
        db.session.commit()

        return jsonify(message=f"status updated for ticket #{ticket_id}")


class NewTicketMessage(Resource):
    """
    Create new message for given ticket.
    """

    def post(self, ticket_id: int):
        # should have subject and description
        tmsg_args = request.form.to_dict()
        tmsg_args['is_team_message'] = "is_team_message" in tmsg_args and tmsg_args['is_team_message'] == "True"
        tmsg_args['ticket_id'] = ticket_id
        tmsg = TicketMessage(**tmsg_args)
        db.session.add(tmsg)
        db.session.commit()

        if tmsg_args['is_team_message']:
            team_name = json.dumps(Team.get_team_name(tmsg.ticket.team_id))
            l.info(
                f"NEW TICKET RESPONSE: ticket_id={ticket_id} message_id={tmsg.id} team_id={tmsg.ticket.team_id} team_name={team_name}")

        return jsonify(message=f"Message for ticket #{ticket_id} added successfully")


class TeamMessageAllowed(Resource):
    """
    Get all the tickets.
    """

    def get(self, ticket_id, team_id):

        if Ticket.check_team(ticket_id, team_id):
            return jsonify(dict(message="permitted"))
        else:
            return jsonify(dict(message="unauthorized attempt to add a message"))


class TicketList(Resource):
    """
    Get all the tickets.
    """

    def get(self):
        tickets = db.session.query(Ticket).order_by(Ticket.created_on.desc()).all()
        return jsonify(dict(
            tickets=[ticket.to_json() for ticket in tickets]
        ))


class TeamTicketList(Resource):
    """
    Get all the tickets for specified team.
    """

    def get(self, team_id):
        tickets = db.session.query(Ticket).filter_by(team_id=team_id).order_by(Ticket.created_on.desc()).all()
        return jsonify(dict(
            tickets=[ticket.to_json() for ticket in tickets]
        ))


class TicketMessagesList(Resource):
    """
    Get all the tickets for specified team.
    """

    def get(self, team_id):
        tickets = db.session.query(Ticket).filter_by(team_id=team_id).all()
        return jsonify(dict(
            tickets=[ticket.to_json() for ticket in tickets]
        ))


# #######################
# --> Ticket Data Objects
# #######################

class Ticket(db.Model):
    """
    tickets opened by a team
    """

    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    subject = db.Column(db.String(128), nullable=False)
    description = db.Column(db.String(4096), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)
    messages = db.relationship("TicketMessage", back_populates="ticket")

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        status = TicketStatus.get_current_status(self.id)
        team_name = Team.get_team_name(self.team_id)

        return dict(
            id=self.id,
            team_id=self.team_id,
            team_name=team_name,
            subject=self.subject,
            description=self.description,
            created_on=self.created_on.isoformat("T") + "Z",
            status=status,
            messages=[s.to_json() for s in self.messages],
        )

    @staticmethod
    def check_team(ticket_id, team_id):
        results = db.session.query(Ticket).filter_by(id=ticket_id, team_id=team_id).all()
        if results:
            return True
        return False


class TicketMessage(db.Model):
    """
    messages on a ticket
    """

    __tablename__ = "ticket_messages"

    id = db.Column(db.Integer, primary_key=True)
    is_team_message = db.Column(db.Boolean, nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    ticket = db.relationship("Ticket", back_populates="messages")

    message_text = db.Column(db.String(4096), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return dict(
            id=self.id,
            is_team_message=self.is_team_message,
            ticket_id=self.ticket_id,
            message_text=self.message_text,
            created_on=self.created_on.isoformat("T") + "Z",
        )


class TicketStatusTypes(enum.Enum):
    OPEN = 1
    CLOSED = 2

    @staticmethod
    def get_text_status(status_val):
        if status_val == TicketStatusTypes.OPEN:
            return "OPEN"
        elif status_val == TicketStatusTypes.CLOSED:
            return "CLOSED"

    @staticmethod
    def is_valid(test_type):
        valid_strs = ['OPEN', 'CLOSED']
        return test_type.upper() in valid_strs


class TicketStatus(db.Model):
    """
    Current status of a ticket
    """

    id = db.Column(db.Integer, primary_key=True)
    status = db.Column("status", db.Enum(TicketStatusTypes), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_current_status(ticket_id):
        status = db.session.query(TicketStatus).filter_by(ticket_id=ticket_id).order_by(
            TicketStatus.created_on.desc()).first()
        if not status:
            raise Exception("Ruh roh, no status on ticket, this is bad.")

        return TicketStatusTypes.get_text_status(status.status)

    @staticmethod
    def create_default_status(ticket_id):
        params = dict(status=TicketStatusTypes.OPEN, ticket_id=ticket_id)
        return TicketStatus(**params)


##########################################################################
####                 SOLD OUT (no more ticket classes)                ####
##########################################################################

class TickTime(db.Model):
    """
    current time that a tick should last. Allows us to control.
    """

    __tablename__ = "tick_times"

    _DEFAULT_TICK_TIME = 600

    id = db.Column(db.Integer, primary_key=True)
    time_seconds = db.Column(db.Integer, nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_current_tick_time():
        current_tick_time = db.session.query(TickTime).order_by(TickTime.id.desc()).first()
        if current_tick_time:
            return current_tick_time.time_seconds
        else:
            return TickTime._DEFAULT_TICK_TIME


class IsGameStatePublic(db.Model):
    """
    Is the game state public? Allows us to control.
    """

    __tablename__ = "is_game_state_public"

    _DEFAULT_VALUE = False

    id = db.Column(db.Integer, primary_key=True)
    is_game_state_public = db.Column(db.Boolean, nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_current_is_game_state_public():
        current_is_game_state_public = db.session.query(IsGameStatePublic).order_by(IsGameStatePublic.id.desc()).first()
        if current_is_game_state_public:
            return current_is_game_state_public.is_game_state_public
        else:
            return IsGameStatePublic._DEFAULT_VALUE


class GameStateDelay(db.Model):
    """
    current time that a tick should last. Allows us to control.
    """

    __tablename__ = "game_state_delays"

    _DEFAULT_VALUE = 2

    id = db.Column(db.Integer, primary_key=True)
    game_state_delay = db.Column(db.Integer, nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_current_game_state_delay():
        current_game_state_delay = db.session.query(GameStateDelay).order_by(GameStateDelay.id.desc()).first()
        if current_game_state_delay:
            return current_game_state_delay.game_state_delay
        else:
            return GameStateDelay._DEFAULT_VALUE


class Tick(db.Model):
    """
    Tick in the game corresponds to some length of time.
    """

    __tablename__ = "ticks"

    id = db.Column(db.Integer, primary_key=True)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False, index=True)
    flags = db.relationship("Flag", back_populates='tick')
    flag_submissions = db.relationship("FlagSubmission", back_populates='tick')
    events = db.relationship("Event", back_populates='tick')

    @staticmethod
    def get_current_tick():
        current_tick = db.session.query(Tick).order_by(Tick.id.desc()).first()
        return current_tick

    @staticmethod
    def get_tick_at(timestamp):
        current_tick = db.session.query(Tick).filter(Tick.created_on <= timestamp).order_by(Tick.id.desc()).first()
        return current_tick

    @staticmethod
    def get_current_tick_id():
        return Tick.get_current_tick().id

    def to_json(self):
        """
        Return the JSON representation of the tick.
        """

        return dict(
            id=self.id,
            created_on=self.created_on
        )


class State(enum.Enum):
    INIT = 0
    RUNNING = 1
    PAUSED = 2
    STOPPED = 3

    @classmethod
    def to_json(cls, data):
        return State[data]


class GameState(db.Model):
    """
    Current state of the game
    """

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column("state", db.Enum(State), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_current_state():
        state = db.session.query(GameState).order_by(GameState.id.desc()).first()
        if not state:
            raise Exception("Ruh roh, no initial state, this is bad.")
        return state


class Team(db.Model):
    """
    Team.
    """

    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(1024), nullable=False)
    team_network = db.Column(db.String(128), nullable=False)
    vm_address = db.Column(db.String(20), nullable=False)
    is_test_team = db.Column(db.Boolean, default=False, nullable=False)

    flags = db.relationship("Flag", back_populates="team")
    exploit_script_events = db.relationship("ExploitScriptEvent", back_populates="team")
    sla_script_events = db.relationship("SlaScriptEvent", back_populates="team")
    set_flag_events = db.relationship("SetFlagEvent", back_populates="team")
    flag_exploit_events = db.relationship("FlagStolenEvent", foreign_keys='FlagStolenEvent.exploit_team_id',
                                          back_populates="exploit_team")
    flag_victim_events = db.relationship("FlagStolenEvent", foreign_keys='FlagStolenEvent.victim_team_id',
                                         back_populates="victim_team")
    koh_score_fetch_events = db.relationship("KohScoreFetchEvent", back_populates="team")
    koh_rank_results = db.relationship("KohRankResult", back_populates="team")
    pcap_released_events = db.relationship("PcapReleasedEvent", back_populates="team")
    outgoing_stealth_events = db.relationship("StealthEvent", foreign_keys='StealthEvent.src_team_id',
                                              back_populates="src_team")
    incoming_stealth_events = db.relationship("StealthEvent", foreign_keys='StealthEvent.dst_team_id',
                                              back_populates="dst_team")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    @staticmethod
    def get_team_name(team_id):
        team = db.session.query(Team).filter_by(id=team_id).first()
        return team.name

    def get_is_test_team(team_id):
        team = db.session.query(Team).filter_by(id=team_id).first()
        return team.is_test_team

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """

        return dict(id=self.id,
                    name=self.name,
                    team_network=self.team_network,
                    vm_address=self.vm_address,
                    is_test_team=self.is_test_team,
                    created_on=self.created_on)


class EventType(enum.Enum):
    EXPLOIT_SCRIPT = 1
    SLA_SCRIPT = 2
    FLAG_STOLEN = 3
    SET_FLAG = 4
    KOH_SCORE_FETCH = 5
    KOH_RANKING = 6
    PCAP_CREATED = 7
    PCAP_RELEASED = 8
    STEALTH = 9


class Event(db.Model):
    """
    An event in the game.
    """
    __tablename__ = "events"

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.Integer, nullable=False, index=True)
    reason = db.Column(db.String(2048), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)
    tick = db.relationship("Tick", back_populates="events")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (db.Index('idx_event_event_type_tick_id', 'event_type', 'tick_id'),)

    __mapper_args__ = {
        'polymorphic_identity': 'events',
        'polymorphic_on': event_type
    }

    def to_json(self):
        return dict(id=self.id,
                    event_type=EventType(self.event_type).name,
                    reason=self.reason,
                    tick_id=self.tick_id,
                    created_on=self.created_on,
                    )


class ScriptResult(enum.Enum):
    SUCCESS = 1
    FAIL = 2


class ExploitScriptEvent(Event):
    """
    An exploit script event.
    """
    __tablename__ = "exploit_script_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="exploit_script_events")
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)

    service = db.relationship("Service", back_populates="exploit_script_events")

    ip = db.Column(db.String(128), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    service_interaction_docker = db.Column(db.String(1028), nullable=False)
    the_script = db.Column(db.String(2048), nullable=False)
    docker_registry = db.Column(db.String(2048), nullable=True)
    result = db.Column("result", db.Enum(ScriptResult), nullable=False, index=True)

    __mapper_args__ = {
        'polymorphic_identity': EventType.EXPLOIT_SCRIPT.value
    }

    def to_json(self):
        parent = super(ExploitScriptEvent, self).to_json()
        return dict(team_id=self.team_id,
                    service_id=self.service_id,
                    ip=self.ip,
                    port=self.port,
                    service_interaction_docker=self.service_interaction_docker,
                    the_script=self.the_script,
                    docker_registry=self.docker_registry,
                    result=self.result.name,
                    **parent
                    )


class SlaScriptEvent(Event):
    """
    An sla script event.
    """
    __tablename__ = "sla_script_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="sla_script_events")
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="sla_script_events")

    ip = db.Column(db.String(128), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    service_interaction_docker = db.Column(db.String(1028), nullable=False)
    the_script = db.Column(db.String(2048), nullable=False)
    docker_registry = db.Column(db.String(2048), nullable=True)
    result = db.Column("result", db.Enum(ScriptResult), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': EventType.SLA_SCRIPT.value
    }

    def to_json(self):
        parent = super(SlaScriptEvent, self).to_json()
        return dict(team_id=self.team_id,
                    service_id=self.service_id,
                    ip=self.ip,
                    port=self.port,
                    service_interaction_docker=self.service_interaction_docker,
                    the_script=self.the_script,
                    docker_registry=self.docker_registry,
                    result=self.result.name,
                    **parent
                    )


class SetFlagResult(enum.Enum):
    SUCCESS = 1
    FAIL = 2


class SetFlagEvent(Event):
    """
    A flag was set.
    """
    __tablename__ = "set_flag_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="set_flag_events")
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="set_flag_events")
    flag_id = db.Column(db.Integer, db.ForeignKey('flags.id'), nullable=False)
    flag = db.relationship("Flag", back_populates="set_flag_events")
    result = db.Column("result", db.Enum(SetFlagResult), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': EventType.SET_FLAG.value
    }

    def to_json(self):
        parent = super(SetFlagEvent, self).to_json()
        return dict(team_id=self.team_id,
                    service_id=self.service_id,
                    flag_id=self.flag_id,
                    result=self.result.name,
                    **parent
                    )


class FlagStolenEvent(Event):
    """
    A flag was stolen.
    """

    __tablename__ = "flag_stolen_events"
    __table_args__ = (
        db.UniqueConstraint('exploit_team_id', 'flag_id'),
    )

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)

    exploit_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    exploit_team = db.relationship("Team", foreign_keys=exploit_team_id, back_populates="flag_exploit_events")
    victim_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    victim_team = db.relationship("Team", foreign_keys=victim_team_id, back_populates="flag_victim_events")
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="flag_stolen_events")
    flag_id = db.Column(db.Integer, db.ForeignKey('flags.id'), nullable=False)
    flag = db.relationship("Flag", back_populates="flag_stolen_events")

    __mapper_args__ = {
        'polymorphic_identity': EventType.FLAG_STOLEN.value
    }

    def to_json(self):
        parent = super(FlagStolenEvent, self).to_json()
        return dict(exploit_team_id=self.exploit_team_id,
                    victim_team_id=self.victim_team_id,
                    service_id=self.service_id,
                    flag_id=self.flag_id,
                    **parent
                    )


class KohScoreFetchResult(enum.Enum):
    SUCCESS = 1
    FAIL = 2


class KohScoreFetchEvent(Event):
    """
    Result of fetching koh score from a service.
    Just used as game-time debugging.
    """

    __tablename__ = "koh_score_fetch_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="koh_score_fetch_events")
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="koh_score_fetch_events")
    score = db.Column(db.Integer, nullable=True)
    data = db.Column(db.String(1024), nullable=True)
    result = db.Column("result", db.Enum(KohScoreFetchResult), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': EventType.KOH_SCORE_FETCH.value
    }

    @db.validates('score')
    def validate_score(self, key, score):
        if self.result == KohScoreFetchResult.SUCCESS:
            assert score
        return score

    def to_json(self):
        parent = super(KohScoreFetchEvent, self).to_json()
        return dict(team_id=self.team_id,
                    service_id=self.service_id,
                    score=self.score,
                    data=self.data,
                    result=self.result.name,
                    **parent
                    )


class KohRankResult(db.Model):
    """
    One team's rank on one service for a given KohRanking Event
    """

    __tablename__ = "koh_ranking_results"

    id = db.Column(db.Integer, primary_key=True)
    rank = db.Column(db.Integer, nullable=False, index=True)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="koh_rank_results")
    koh_ranking_event_id = db.Column(db.Integer, db.ForeignKey('koh_ranking_events.id'), nullable=False)
    koh_ranking_event = db.relationship("KohRankingEvent", back_populates="koh_rank_results")
    score = db.Column(db.Integer, nullable=False)
    data = db.Column(db.String(1024), nullable=True)

    __table_args__ = (db.Index('idx_rank_koh_ranking_event_id', 'rank', 'koh_ranking_event_id'),)

    @db.validates('rank')
    def validate_type_interaction_docker(self, key, rank):
        assert rank > 0
        return rank

    def to_json(self):
        return dict(id=self.id,
                    rank=self.rank,
                    team_id=self.team_id,
                    score=self.score,
                    data=self.score,
                    )


class KohRankingEvent(Event):
    """
    The result of a round of ranking a KoH service.
    """

    __tablename__ = "koh_ranking_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="koh_ranking_events")
    koh_rank_results = db.relationship("KohRankResult", back_populates="koh_ranking_event")

    __mapper_args__ = {
        'polymorphic_identity': EventType.KOH_RANKING.value
    }

    def to_json(self):
        parent = super(KohRankingEvent, self).to_json()
        return dict(service_id=self.service_id,
                    ranking=[result.to_json() for result in self.koh_rank_results],
                    **parent
                    )


class PcapCreatedEvent(Event):
    """
    A pcap was created from the router and put on the pcap processing system
    """

    __tablename__ = "pcap_created_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    pcap_name = db.Column(db.String(2048), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': EventType.PCAP_CREATED.value
    }

    def to_json(self):
        parent = super(PcapCreatedEvent, self).to_json()
        return dict(service_id=self.service_id,
                    team_id=self.team_id,
                    pcap_name=self.pcap_name,
                    **parent
                    )


class PcapReleasedEvent(Event):
    """
    A pcap was created from the router and put on the pcap processing system
    """

    __tablename__ = "pcap_released_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)
    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    service = db.relationship("Service", back_populates="pcap_released_events")
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    team = db.relationship("Team", back_populates="pcap_released_events")
    pcap_name = db.Column(db.String(2048), nullable=False)

    __mapper_args__ = {
        'polymorphic_identity': EventType.PCAP_RELEASED.value
    }

    def to_json(self):
        parent = super(PcapReleasedEvent, self).to_json()
        return dict(service_id=self.service_id,
                    team_id=self.team_id,
                    pcap_name=self.pcap_name,
                    **parent
                    )


class StealthEvent(Event):
    """
    Traffic was detected on a team stealth port.
    """

    __tablename__ = "stealth_events"

    id = db.Column(db.Integer, db.ForeignKey('events.id'), primary_key=True)

    service_id = db.Column(db.Integer, db.ForeignKey('services.id'), nullable=False)
    src_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    dst_team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), nullable=False, index=True)

    service = db.relationship("Service", back_populates="stealth_events")
    src_team = db.relationship("Team", foreign_keys=src_team_id, back_populates="outgoing_stealth_events")
    dst_team = db.relationship("Team", foreign_keys=dst_team_id, back_populates="incoming_stealth_events")

    __mapper_args__ = {
        'polymorphic_identity': EventType.STEALTH.value
    }

    __table_args__ = (
        db.Index('idx_stealth_team_service', 'service_id', 'src_team_id', 'dst_team_id', 'tick_id'),
        db.UniqueConstraint('service_id', 'src_team_id', 'dst_team_id', 'tick_id'),
    )

    def to_json(self):
        parent = super(StealthEvent, self).to_json()
        return dict(
            service_id=self.service_id,
            src_team_id=self.src_team_id,
            dst_team_id=self.dst_team_id,
            **parent
        )


class ServiceType(enum.Enum):
    NORMAL = 0
    KING_OF_THE_HILL = 1


class IsolationType(enum.Enum):
    SHARED = 0
    PRIVATE = 1

    def to_json(self):
        return self.name


class ExploitScriptPath(db.Model):
    """
    The location of exploit scripts.
    """
    __tablename__ = "exploit_script_paths"

    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(2048), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    service = db.relationship("Service", back_populates="exploit_scripts")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return self.path


class SlaScriptPath(db.Model):
    """
    The location of the SLA scripts.
    """
    __tablename__ = "sla_script_paths"
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(2048), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    service = db.relationship("Service", back_populates="sla_scripts")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return self.path


class LocalInteractionScriptPath(db.Model):
    """
    The location of the local interaction scripts.
    """
    __tablename__ = "local_interaction_script_paths"
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(2048), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    service = db.relationship("Service", back_populates="local_interaction_scripts")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return self.path


class TestScriptPath(db.Model):
    """
    The location of the SLA scripts.
    """
    __tablename__ = "test_script_paths"
    id = db.Column(db.Integer, primary_key=True)
    path = db.Column(db.String(2048), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    service = db.relationship("Service", back_populates="test_scripts")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return self.path


class ReleasePcaps(db.Model):
    """
    Should the pcaps of the service be released?
    """

    __tablename__ = "release_pcaps"
    id = db.Column(db.Integer, primary_key=True)
    release_pcaps = db.Column(db.Boolean, nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)


class IsVisible(db.Model):
    """
    Is the service visible?

    This decides if the service should show up on any externally-facing place (scoreboard, etc.)

    """

    __tablename__ = "is_visible"
    id = db.Column(db.Integer, primary_key=True)
    is_visible = db.Column(db.Boolean, nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)


class IsActive(db.Model):
    """
    Is the service active?

    This decides if the service should be included in scoring: Can
    flags be submitted for points? Should the service be considered for defensive points?

    """

    __tablename__ = "is_active"
    id = db.Column(db.Integer, primary_key=True)
    is_active = db.Column(db.Boolean, nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    __table_args__ = (db.Index('idx_is_active_service_id_tick_id', 'service_id', 'tick_id'),)


# Did not give us a perf improvement
class CacheWasServiceActive(db.Model):
    """
    This tables caches the calculation of the "was_service_active" calculation
    """

    __tablename__ = "cache_was_service_active"
    id = db.Column(db.Integer, primary_key=True)
    was_active = db.Column(db.Boolean, nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    __table_args__ = (db.Index('idx_cache_was_service_active_service_id_tick_id', 'service_id', 'tick_id'),)


class CacheTickScores(db.Model):
    """
    This tables caches the calculation of the "calculate_scores"
    """

    __tablename__ = "cache_calculate_scores"
    id = db.Column(db.Integer, primary_key=True)
    score_json = db.Column(db.String(4096), nullable=False)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now)


class ServiceStatus(enum.Enum):
    GOOD = 0
    OK = 1
    LOW = 2
    BAD = 3

    def to_emoji(self):
        mapping = {ServiceStatus.GOOD: "🟢",
                   ServiceStatus.OK: "🟡",
                   ServiceStatus.LOW: "🟠",
                   ServiceStatus.BAD: "🔴",
                   }
        return mapping[self]


class StatusIndicator(db.Model):
    """
    What is the current state of the service?

    This is just a rough indicator to the teams about how close the service is to be retired.
    """

    __tablename__ = "status_indicators"

    id = db.Column(db.Integer, primary_key=True)
    service_status = db.Column(db.Enum(ServiceStatus), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)


class Service(db.Model):
    """
    Service.
    """

    __tablename__ = "services"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=False)
    description = db.Column(db.String(2048), nullable=False)
    score_location = db.Column(db.String(512), nullable=True)
    repo_url = db.Column(db.String(512), nullable=False)
    type = db.Column("type", db.Enum(ServiceType), nullable=False)
    flag_location = db.Column(db.String(512), nullable=True)
    central_server = db.Column(db.String(1024), nullable=True)
    isolation = db.Column("isolation", db.Enum(IsolationType), nullable=True)
    port = db.Column(db.Integer, nullable=False)
    container_port = db.Column(db.Integer, nullable=True)
    service_docker = db.Column(db.String(1024), nullable=True)
    interaction_docker = db.Column(db.String(1024))
    local_interaction_docker = db.Column(db.String(1024))
    execution_profile = db.Column(db.Text)
    patchable_file_from_docker = db.Column(db.String(1024))
    patchable_file_from_service_dir = db.Column(db.String(1024))
    max_bytes = db.Column(db.Integer)
    check_timeout = db.Column(db.Integer)
    is_manual_patching = db.Column(db.Boolean, default=False)

    flags = db.relationship("Flag", back_populates="service")
    exploit_scripts = db.relationship("ExploitScriptPath", back_populates="service")
    sla_scripts = db.relationship("SlaScriptPath", back_populates="service")
    local_interaction_scripts = db.relationship("LocalInteractionScriptPath", back_populates="service")
    test_scripts = db.relationship("TestScriptPath", back_populates="service")
    exploit_script_events = db.relationship("ExploitScriptEvent", back_populates="service")
    sla_script_events = db.relationship("SlaScriptEvent", back_populates="service")
    set_flag_events = db.relationship("SetFlagEvent", back_populates="service")
    flag_stolen_events = db.relationship("FlagStolenEvent", back_populates="service")
    koh_score_fetch_events = db.relationship("KohScoreFetchEvent", back_populates="service")
    koh_ranking_events = db.relationship("KohRankingEvent", back_populates="service")
    pcap_released_events = db.relationship("PcapReleasedEvent", back_populates="service")
    stealth_events = db.relationship("StealthEvent", back_populates="service")

    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    limit_memory = db.Column(db.String(6), default="512m")
    request_memory = db.Column(db.String(6), default="512m")

    @property
    def release_pcaps(self):
        release_pcaps = db.session.query(ReleasePcaps).filter_by(service_id=self.id).order_by(
            ReleasePcaps.id.desc()).first()
        if release_pcaps:
            return release_pcaps.release_pcaps
        else:
            return False

    @property
    def is_visible(self):
        is_visible = db.session.query(IsVisible).filter_by(service_id=self.id).order_by(IsVisible.id.desc()).first()
        if is_visible:
            return is_visible.is_visible
        else:
            return False

    @property
    def is_active(self):
        is_active = db.session.query(IsActive).filter_by(service_id=self.id).order_by(IsActive.id.desc()).first()
        if is_active:
            return is_active.is_active
        else:
            return False

    @property
    def service_indicator(self):
        service_indicator = db.session.query(StatusIndicator).filter_by(service_id=self.id).order_by(
            StatusIndicator.id.desc()).first()
        if service_indicator:
            return service_indicator.service_status
        else:
            return ServiceStatus.GOOD

    @staticmethod
    def get_num_submitted_patches_for_id(service_id):
        service_patches = db.session.query(UploadedPatch).filter_by(service_id=service_id).all()
        return len(service_patches)

    @staticmethod
    def get_num_accepted_patches_for_id(service_id):
        service_patches = db.session.query(UploadedPatch).filter_by(service_id=service_id).all()
        accepted_patches = 0
        if service_patches:
            accepted_patches = sum(map(lambda a: a.results.first().status == PatchStatus.ACCEPTED, service_patches))
        return accepted_patches

    def was_active(self, tick_id):
        """
        Answers the question: was the service active during the given tick?
        """

        # Check the cache first
        cache = db.session.query(CacheWasServiceActive).filter_by(service_id=self.id,
                                                                  tick_id=tick_id).first()
        if cache:
            return cache.was_active

        result = None
        active_in_tick = db.session.query(IsActive).filter_by(service_id=self.id, tick_id=tick_id).all()
        # Handle the case that there were multiple events
        if active_in_tick:
            result = all(map(lambda a: a.is_active, active_in_tick))
        else:
            # Get the last value
            last_active = db.session.query(IsActive).filter(IsActive.service_id == self.id,
                                                            IsActive.tick_id < tick_id).order_by(
                IsActive.id.desc()).first()

            if last_active:
                result = last_active.is_active
            else:
                # Default is inactive
                result = False

        if is_tick_old_enough_to_cache(tick_id):
            cached = CacheWasServiceActive(was_active=result,
                                           service_id=self.id,
                                           tick_id=tick_id
                                           )
            db.session.add(cached)
            db.session.commit()

        return result

    @db.validates('flag_location')
    def validate_type_interaction_docker(self, key, flag_location):
        if self.type == ServiceType.NORMAL:
            assert flag_location
        return flag_location

    @db.validates('isolation')
    def validate_isolation(self, key, isolation):
        if self.type == ServiceType.NORMAL:
            assert isolation
        return isolation

    @db.validates('score_location')
    def validate_type_interaction_docker(self, key, score_location):
        if self.type == ServiceType.KING_OF_THE_HILL:
            assert score_location
        return score_location

    @db.validates('interaction_docker')
    def validate_type_interaction_docker(self, key, interaction_docker):
        if self.type == ServiceType.NORMAL:
            assert interaction_docker
        return interaction_docker

    @db.validates('service_docker')
    def validate_type_interaction_docker(self, key, service_docker):
        if self.type == ServiceType.NORMAL:
            assert service_docker
        return service_docker

    @db.validates("execution_profile")
    def validate_type_execution_profile(self, key, execution_profile):
        if self.type == ServiceType.NORMAL:
            assert execution_profile
        return execution_profile

    @db.validates('container_port')
    def validate_type_interaction_docker(self, key, container_port):
        if self.type == ServiceType.NORMAL:
            assert container_port
        return container_port

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return dict(id=self.id,
                    name=self.name,
                    repo_url=self.repo_url,
                    exploit_scripts=[s.to_json() for s in self.exploit_scripts],
                    sla_scripts=[s.to_json() for s in self.sla_scripts],
                    local_interaction_scripts=[s.to_json() for s in self.local_interaction_scripts],
                    test_scripts=[s.to_json() for s in self.test_scripts],
                    service_docker=self.service_docker,
                    interaction_docker=self.interaction_docker,
                    local_interaction_docker=self.local_interaction_docker,
                    execution_profile=self.execution_profile,
                    flag_location=self.flag_location,
                    central_server=self.central_server,
                    isolation=self.isolation.to_json() if self.isolation else None,
                    score_location=self.score_location,
                    description=self.description,
                    type=self.type.name,
                    port=self.port,
                    container_port=self.container_port,
                    release_pcaps=self.release_pcaps,
                    is_visible=self.is_visible,
                    is_active=self.is_active,
                    is_manual_patching=self.is_manual_patching,
                    service_indicator=self.service_indicator.name,
                    patchable_file_from_docker=self.patchable_file_from_docker,
                    max_bytes=self.max_bytes,
                    check_timeout=self.check_timeout,
                    patchable_file_from_service_dir=self.patchable_file_from_service_dir,
                    created_on=self.created_on.isoformat("T") + "Z",
                    limit_memory=self.limit_memory,
                    request_memory=self.request_memory,
                    )


class UploadedPatchResult(db.Model):
    """
    The result from testing a patch.
    """

    __tablename__ = "patch_result"

    id = db.Column(db.Integer, primary_key=True)
    patch_id = db.Column(db.Integer, db.ForeignKey('uploaded_patches.id'), nullable=True)
    patch = db.relationship("UploadedPatch", back_populates="results")
    status = db.Column("status", db.Enum(PatchStatus), nullable=False, index=True)
    public_metadata = db.Column(db.String(256), nullable=True)
    private_metadata = db.Column(db.String(256), nullable=True)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return dict(
            id=self.id,
            patch_id=self.patch_id,
            status=self.status.name,
            public_metadata=self.public_metadata,
            private_metadata=self.private_metadata,
            created_on=self.created_on,
        )


class UploadedPatch(db.Model):
    """
    Uploaded service patch.
    """

    __tablename__ = "uploaded_patches"

    id = db.Column(db.Integer, primary_key=True)
    team_id = db.Column(db.Integer, db.ForeignKey("teams.id"), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    uploaded_file = db.deferred(db.Column(db.LargeBinary(length=(2 ** 32) - 1), nullable=False))
    uploaded_hash = db.Column(db.String(256), nullable=False)
    results = db.relationship("UploadedPatchResult", back_populates="patch", lazy='dynamic',
                              order_by="desc(UploadedPatchResult.created_on)")
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False,
                        index=True)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now)

    def to_json(self):
        """
        Return a JSON representation.
        :return: JSON.
        """
        return dict(
            id=self.id,
            team_id=self.team_id,
            service_id=self.service_id,
            uploaded_hash=self.uploaded_hash,
            results=[result.to_json() for result in self.results],
            created_on=self.created_on,
        )

    def to_detailed_json(self):
        """
        Return a JSON representation including the uploaded file.
        :return: JSON.
        """
        result = self.to_json()
        result['uploaded_file'] = base64.b64encode(self.uploaded_file).decode()
        return result


class Flag(db.Model):
    """
    Flags in the game.
    """
    __tablename__ = "flags"

    id = db.Column(db.Integer, primary_key=True)
    flag = db.Column(db.String(256), nullable=False, index=True, unique=True)
    team = db.relationship("Team", back_populates="flags")
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey("services.id"), nullable=False)
    service = db.relationship("Service", back_populates="flags")
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)
    tick = db.relationship("Tick", back_populates="flags")

    set_flag_events = db.relationship("SetFlagEvent", back_populates="flag")
    flag_stolen_events = db.relationship("FlagStolenEvent", back_populates="flag")
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (db.Index('idx_flags_service_id_team_id', 'service_id', 'team_id'),
                      db.Index('idx_flags_service_id_team_id_tick_id', 'service_id', 'team_id', 'tick_id')
                      )

    def to_json(self):
        """
        Return the JSON representation
        :return: JSON.
        """
        return dict(
            id=self.id,
            flag=self.flag,
            team_id=self.team_id,
            service_id=self.service_id,
            tick_id=self.tick_id,
            created_on=self.created_on,
        )


class FlagSubmissionResult(enum.Enum):
    CORRECT = 0
    INCORRECT = 1
    OWN_FLAG = 2
    ALREADY_SUBMITTED = 3
    TOO_OLD = 4
    SERVICE_INACTIVE = 5
    TEST_TEAM_FLAG = 6

    @classmethod
    def to_json(cls, data):
        return FlagSubmissionResult[data]


class FlagSubmission(db.Model):
    """
    Flags in the game.
    """

    __tablename__ = "flag_submissions"

    id = db.Column(db.Integer, primary_key=True)
    submission = db.Column(db.String(256), nullable=False, index=True)
    result = db.Column("result", db.Enum(FlagSubmissionResult), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'), nullable=False)
    flag_id = db.Column(db.Integer, db.ForeignKey('flags.id'), nullable=True)
    tick_id = db.Column(db.Integer, db.ForeignKey('ticks.id'), default=Tick.get_current_tick_id, nullable=False)
    tick = db.relationship("Tick", back_populates="flag_submissions")
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_flag_submissions_submission_team_id', 'submission', 'team_id'),
        db.UniqueConstraint('team_id', 'submission'),
    )

    def to_json(self):
        """
        Return the JSON representation
        :return: JSON.
        """
        return dict(
            id=self.id,
            result=self.result.name,
        )


class Announcement(db.Model):
    """
    XXX: NOT IN USE ANYMORE
    """

    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.String(1024), nullable=False)
    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)

    def to_json(self):
        return dict(
            id=self.id,
            text=self.text,
            created_on=self.created_on)


class Deleted(db.Model):
    """
    This table keeps all of the rows that we deleted during the game
    (if any). This is necessary because in previous years we had to
    delete some flags and other elements, but it's not great because that data
    then disappears. This way, the data (in the form of a json object) will be stored here.
    """

    __tablename__ = "deleted"

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.LargeBinary(length=(2 ** 32) - 1), nullable=False)

    created_on = db.Column(db.DateTime, default=datetime.datetime.now, nullable=False)


def receive_before_delete(mapper, connection, target):
    content = None
    if hasattr(target, "to_json"):
        content = json.dumps(target.to_json())
    else:
        content = f"{target}"
    content = f"{type(target).__name__}: {content}"
    connection.execute("insert into deleted (content, created_on) values (?, ?)", content.encode(),
                       datetime.datetime.now())


# Hook all delete events for all objects
for klass in db.Model.__subclasses__():
    decorator = sqlalchemy.event.listens_for(klass, 'before_delete')
    receive_before_delete = decorator(receive_before_delete)


class TeamList(Resource):
    """
    Team list.
    """

    def get(self):
        """
        GET callback.
        TODO: Ensure that this endpoint does not release secret keys to teams.
        :return: Team list.
        """
        teams = db.session.query(Team).order_by(Team.id)
        return jsonify(dict(teams=[team.to_json() for team in teams if (not team.is_test_team)]))


class TeamPcapList(Resource):
    """
    Get all the pcaps for all the services for a given team.
    """

    def get(self, team_id):
        pcap_released_events = db.session.query(PcapReleasedEvent).filter_by(team_id=team_id)

        return jsonify([event.to_json() for event in pcap_released_events])


class TeamInfo(Resource):
    """
    Info on one team.
    """

    def get(self, team_id):
        team = db.session.query(Team).get(team_id)
        return jsonify(team.to_json())


class TeamFromIP(Resource):
    """
    Return the team that corresponds to a specific IP address or None.
    """

    def get(self, ip):
        address = ipaddress.ip_address(ip)
        team_id = None
        for team in db.session.query(Team):
            team_network = ipaddress.ip_network(team.team_network)
            if address in team_network:
                team_id = team.id
                break

        return jsonify(dict(team_id=team_id))


class PatchInfo(Resource):
    """
    Return information for a specific patch
    """

    def get(self, patch_id: int):
        patch = db.session.query(UploadedPatch).get(patch_id)
        if not patch:
            abort(404, message=f'no patch with id {patch_id} found')

        return jsonify(patch.to_detailed_json())


class TeamUploadedPatchInfo(Resource):
    """
    Team Uploaded Patch Info.
    """

    def get(self, team_id):
        team_patches = db.session.query(UploadedPatch).filter_by(team_id=team_id)
        return jsonify(patches=[tp.to_json() for tp in team_patches])


class UploadPatch(Resource):
    """
    Uploaded Patch.
    """

    def post(self):
        patch_args = request.form.to_dict()

        service = db.session.query(Service).get(patch_args['service_id'])
        if not service:
            abort(400, message="no such service")

        if not service.is_active:
            abort(400, message="service is not active")

        if not service.type == ServiceType.NORMAL:
            abort(400, message="only patching normal services")

        patch_exists = db.session.query(UploadedPatch) \
            .filter_by(team_id=patch_args['team_id'],
                       service_id=patch_args['service_id'],
                       tick_id=Tick.get_current_tick_id()) \
            .order_by(UploadedPatch.id) \
            .first()
        if patch_exists:
            return jsonify(message='already uploaded this tick for this service')

        file_data = request.files['uploaded_file'].read()

        m = hashlib.sha256()
        m.update(file_data)
        file_hash = m.hexdigest()

        patch_args['uploaded_file'] = file_data
        patch_args['uploaded_hash'] = file_hash

        patch = UploadedPatch(**patch_args)
        db.session.add(patch)

        first_status = UploadedPatchResult(patch=patch, status=PatchStatus.SUBMITTED, public_metadata=None,
                                           private_metadata=f"accepted by the database api.")
        db.session.add(first_status)

        db.session.commit()

        # queue the patching test
        if service.is_manual_patching:
            l.info(f"MANUAL PATCH REVIEW: patch_id={patch.id} team_id={patch_args['team_id']}")
        else:
            queue_name = 'default'
            # HARDCODED FOR ALL OOOWS CHALLENGES
            if service.central_server == 'ooows-depot':
                queue_name = 'ooows'
            rq.get_queue(queue_name).enqueue(patchbot.test_patch, patch.id, job_timeout=700,
                                   mem_limit=service.limit_memory, mem_reservation=service.request_memory)

        return jsonify(message='upload successful')


class NewPatchStatus(Resource):
    """
    Set a new patch status.
    """

    def post(self, patch_id):
        args = request.form.to_dict()
        args['patch_id'] = patch_id
        args['status'] = PatchStatus[args['status']]
        result = UploadedPatchResult(**args)
        db.session.add(result)
        db.session.commit()
        return jsonify(result.to_json())


class GenerateFlag(Resource):
    """
    Generate a flag for the given service and team
    """

    def _generate_new_flag(self):
        """Generate a new flag, based on the game settings.

        :return: Flag following the predefined flag format.
        """
        flag = "".join(random.choice(app.config["FLAG_ALPHABET"])
                       for _ in range(app.config["FLAG_LENGTH"]))
        return "{0[FLAG_PREFIX]}{1}{0[FLAG_SUFFIX]}".format(app.config, flag)

    def post(self, service_id: int, team_id: int):
        team = db.session.query(Team).get(team_id)
        if not team:
            abort(400, message="invalid team id")
        service = db.session.query(Service).get(service_id)
        if not service:
            abort(400, message="invalid service id")

        # Check, is there a tick?

        tick = Tick.get_current_tick()
        if not tick:
            abort(400, message="there is no tick, can't generate a flag")

        # If there's already a flag for this team, service, tick, then return that
        already_flag = db.session.query(Flag).filter_by(team_id=team_id, service_id=service_id, tick_id=tick.id).first()
        if already_flag:
            return jsonify(already_flag.to_json())

        the_flag = self._generate_new_flag()

        flag = Flag(team_id=team_id,
                    service_id=service_id,
                    flag=the_flag,
                    )
        db.session.add(flag)
        db.session.commit()

        return jsonify(flag.to_json())


class GetLatestFlag(Resource):
    """
    Get the last valid flag for the service
    """

    def get(self, service_id, team_id):
        the_flag = db.session.query(Flag).filter_by(service_id=service_id, team_id=team_id).order_by(
            Flag.id.desc()).first()
        if not the_flag:
            abort(400, message="Couldn't find an active flag.")
        return jsonify(the_flag.to_json())


class FlagsForTick(Resource):
    """
    Get all flags for a tick
    """

    def get(self, tick_id: int):
        flags = db.session.query(Flag).filter_by(tick_id=tick_id).all()
        return jsonify([f.to_json() for f in flags])


class SubmitFlag(Resource):
    """
    Submit a flag
    """

    def post(self, team_id: int):
        team = db.session.query(Team).get(team_id)
        if not team:
            abort(400, message="invalid team id")

        the_flag = request.form["flag"]
        if not the_flag:
            abort(400, message="must submit a flag")

        tick = Tick.get_current_tick()
        if not tick:
            abort(400, message="Cannot submit flag without a tick")

        # is it already submitted by this team?
        num_prior_submission = db.session.query(FlagSubmission).filter(FlagSubmission.submission == the_flag,
                                                                       FlagSubmission.team_id == team_id).count()
        if num_prior_submission >= 1:
            # since this was already submitted we don't store it
            return jsonify(dict(result=FlagSubmissionResult.ALREADY_SUBMITTED.name))

        flag_submission = FlagSubmission(submission=the_flag, team_id=team_id)

        # is the flag valid?
        flags = db.session.query(Flag).filter(Flag.flag == the_flag).all()

        if len(flags) == 0:
            flag_submission.result = FlagSubmissionResult.INCORRECT
        elif len(flags) > 1:
            abort(500, message="error with flag submissions, got too many")
        else:
            flag = flags[0]

            # is the service active?
            if not flag.service.is_active:
                db.session.rollback()
                return jsonify(dict(result=FlagSubmissionResult.SERVICE_INACTIVE.name))

            # is it their own flag?
            if flag.team.id == team.id:
                flag_submission.result = FlagSubmissionResult.OWN_FLAG
            # is it the test team's flag
            elif flag.team.is_test_team == True:
                flag_submission.result = FlagSubmissionResult.TEST_TEAM_FLAG
            elif (flag.tick_id + NUM_TICKS_FLAG_VALID_FOR) < Tick.get_current_tick_id():
                flag_submission.result = FlagSubmissionResult.TOO_OLD
            else:
                # Correct!
                flag_submission.result = FlagSubmissionResult.CORRECT
                flag_submission.flag_id = flag.id
                # Was this the first team to exploit this service?
                prior_exploitation = db.session.query(FlagStolenEvent).filter_by(service_id=flag.service.id).first()
                if not prior_exploitation:
                    exploit_team_name = json.dumps(Team.get_team_name(team_id))
                    victim_team_name = json.dumps(Team.get_team_name(flag.team.id))
                    l.info(
                        f"FIRST BLOOD: service_id={flag.service.id} service_name={flag.service.name} exploit_team_id={team_id} exploit_team_name={exploit_team_name} victim_team_name={victim_team_name} victim_team_id={flag.team.id}")

                # Create the event
                # Important: the flagstolenevent's tick_id is when the flag was created. Hopefully this won't cause
                #            problems in the future
                event = FlagStolenEvent(event_type=EventType.FLAG_STOLEN.value,
                                        reason="Team {} stole flag from team {} for service {}".format(team_id,
                                                                                                       flag.team.id,
                                                                                                       flag.service.id),
                                        tick_id=flag.tick.id,
                                        exploit_team_id=team_id,
                                        victim_team_id=flag.team.id,
                                        service_id=flag.service.id,
                                        flag_id=flag.id,
                                        )
                db.session.add(event)

        db.session.add(flag_submission)
        db.session.commit()
        return jsonify(flag_submission.to_json())


class StateOfTheGame(Resource):
    """
    functions to get the current game state
    """

    def get(self):
        current_state = GameState.get_current_state()

        tick_time = TickTime.get_current_tick_time()

        current_tick = Tick.get_current_tick()
        current_tick_id = None
        current_tick_created_on = None
        est_time_remaining = None
        if current_tick:
            current_tick_id = current_tick.id
            delta = datetime.timedelta(seconds=tick_time)
            est_time_done = current_tick.created_on + delta
            est_time_remaining = max(0, (est_time_done - datetime.datetime.now()).total_seconds())
            current_tick_created_on = current_tick.created_on

        is_game_state_public = IsGameStatePublic.get_current_is_game_state_public()
        game_state_delay = GameStateDelay.get_current_game_state_delay()
        return jsonify(dict(
            state=current_state.state.name,
            tick=current_tick_id,
            tick_time_seconds=tick_time,
            is_game_state_public=is_game_state_public,
            game_state_delay=game_state_delay,
            estimated_tick_time_remaining=est_time_remaining,
            current_tick_created_on=current_tick_created_on,
        ))

    def post(self):
        new_state = request.form['state']
        if not new_state:
            abort(400, message="error, must POST the new state")

        try:
            state = State[new_state]
            gs = GameState(state=state)
            db.session.add(gs)
            db.session.commit()
        except KeyError as e:
            abort(400, message="invalid state type, must be one of {}".format(" ".join(State.__members__.keys())))


class StartGame(Resource):
    """
    start the game!
    """

    def post(self):
        current_state = GameState.get_current_state()
        if current_state.state != State.INIT:
            abort(400, message="game state is not in INIT state, it is in {}".format(current_state.state.name))

        gs = GameState(state=State.RUNNING)
        tick = Tick()
        db.session.add(gs)
        db.session.add(tick)
        db.session.commit()

        return jsonify(dict(
            tick=tick.id,
        ))


class NewTick(Resource):
    """
    advance the game state to a new tick!
    """

    def post(self):
        tick = Tick()
        db.session.add(tick)
        db.session.commit()
        l.info(f"NEW TICK: new_tick={tick.id}")
        return jsonify(dict(
            tick=tick.id,
        ))


class ChangeTickTime(Resource):
    """
    Change the length of time for ticks.
    """

    def post(self):
        new_tick_time_seconds = request.form['tick_time_seconds']
        if not new_tick_time_seconds:
            abort(400, message="must POST a tick_time_seconds")

        new_tick_time = TickTime(time_seconds=new_tick_time_seconds)

        db.session.add(new_tick_time)
        db.session.commit()


class ChangeIsGameStatePublic(Resource):
    """
    Change if the game state is released to the teams.
    """

    def post(self, value):
        if not (1 == value or 0 == value):
            abort(400, "error, value must be either 0 or 1")
        is_game_state_public = IsGameStatePublic(is_game_state_public=value == 1)
        db.session.add(is_game_state_public)
        db.session.commit()

        return jsonify(id=is_game_state_public.id)


class ChangeGameStateDelay(Resource):
    """
    Change if the game state is released to the teams.
    """

    def post(self, value):
        if (value < 0):
            abort(400, "error, value must be >= 0")
        game_state_delay = GameStateDelay(game_state_delay=value)
        db.session.add(game_state_delay)
        db.session.commit()

        return jsonify(id=game_state_delay.id)


class ServiceList(Resource):
    """
    Get the list of services.
    """

    def get(self):
        services = db.session.query(Service).all()
        return jsonify(dict(
            services=[service.to_json() for service in services]
        ))


class ServiceInfo(Resource):
    """
    Get the info for a specific service.
    """

    def get(self, service_id):
        service = db.session.query(Service).get(service_id)
        return jsonify(service.to_json())


class ReleaseServicePcaps(Resource):
    """
    Release the pcaps for a given service. value should be 1 to release or 0 to not
    """

    def post(self, service_id, value):
        if not (1 == value or 0 == value):
            abort(400, message="error, value must be either 0 or 1")
        release_pcaps = ReleasePcaps(service_id=service_id, release_pcaps=value == 1)
        db.session.add(release_pcaps)
        db.session.commit()

        return jsonify(id=release_pcaps.id)


class ServiceIsActive(Resource):
    """
    Set if the service is active or not.
    """

    def post(self, service_id, value):
        if not (1 == value or 0 == value):
            abort(400, message="error, value must be either 0 or 1")
        is_active = IsActive(service_id=service_id, is_active=value == 1)
        db.session.add(is_active)
        db.session.commit()

        return jsonify(id=is_active.id)


class ServiceIsVisible(Resource):
    """
    Set if the service is visible or not.
    """

    def post(self, service_id, value):
        if not (1 == value or 0 == value):
            abort(400, message="error, value must be either 0 or 1")
        is_visible = IsVisible(service_id=service_id, is_visible=value == 1)
        db.session.add(is_visible)
        db.session.commit()

        return jsonify(id=is_visible.id)


class SetServiceIndicator(Resource):
    """
    Set the service's indicator status.
    """

    def post(self, service_id, value):
        try:
            new_state = ServiceStatus[value]
        except KeyError as e:
            abort(400, message="invalid service indicator, must be one of {}".format(
                " ".join(ServiceStatus.__members__.keys())))

        indicator = StatusIndicator(service_status=new_state, service_id=service_id)
        db.session.add(indicator)
        db.session.commit()

        service = db.session.query(Service).get(service_id)
        service_name = json.dumps(service.name)
        l.info(
            f"NEW SERVICE STATE: service_id={service_id} service_name={service_name} service_status={new_state.name} status_emoji={new_state.to_emoji()}")

        return jsonify(id=indicator.id)


class SetServiceProfile(Resource):
    """
    Set a service execution profile.
    """

    def post(self, service_id):
        service = db.session.query(Service).get(service_id)
        if not service:
            abort(404, message="Service not found")
        service.execution_profile = request.get_json()
        db.session.commit()


class ScoreType(enum.Enum):
    ATTACK = 0
    DEFENSE = 1
    KING_OF_THE_HILL = 2


def calculate_scores(db, tick_id):
    """
    For a given tick, calculate the scores of all the teams, based on the scoring algorithm.
    TODO: move this into a separate module.
    """

    # cache = db.session.query(CacheTickScores).filter_by(tick_id=tick_id).first()
    # if cache:
    #     return dict(tick_id=tick_id,
    #                 teams=json.loads(cache.score_json))

    teams = db.session.query(Team).all()
    services = db.session.query(Service).all()

    flag_stolen_events = db.session.query(FlagStolenEvent).filter_by(tick_id=tick_id)
    koh_ranking_events = db.session.query(KohRankingEvent).filter_by(tick_id=tick_id)
    stealth_events = db.session.query(StealthEvent).filter_by(tick_id=tick_id)

    active_normal_services = [s for s in services if s.type == ServiceType.NORMAL and s.was_active(tick_id)]
    active_koh_services_id = set(
        s.id for s in services if s.type == ServiceType.KING_OF_THE_HILL and s.was_active(tick_id))
    to_return = dict()
    was_team_exploited = dict()
    # initialize the result
    initial_service_mapping = {}
    was_service_exploited = {}

    active_normal_service_ids = set()

    for service in active_normal_services:
        active_normal_service_ids.add(service.id)
        initial_service_mapping[service.id] = False
        was_service_exploited[service.id] = False

    test_teams = set()
    for team in teams:
        if team.is_test_team:
            test_teams.add(team.id)
            continue  # skip over the test teams when displaying score

        to_return[team.id] = {"id": team.id,
                              ScoreType.ATTACK.name: 0,
                              ScoreType.DEFENSE.name: 0,
                              ScoreType.KING_OF_THE_HILL.name: 0,
                              "service_attack": {},
                              "koh_points_by_service": {}
                              }
        was_team_exploited[team.id] = initial_service_mapping.copy()

    stealthy_tuples = set((e.src_team_id, e.dst_team_id, e.service_id) for e in stealth_events)
    # pytype: disable=attribute-error
    # pytype: disable=unsupported-operands

    for event in flag_stolen_events:

        if event.victim_team_id in test_teams or event.exploit_team_id in test_teams:
            continue  # skip events involving the test team

        if not event.service_id in active_normal_service_ids:
            continue

        was_team_exploited[event.victim_team_id][event.service_id] = True
        was_service_exploited[event.service.id] = True
        score = 0.5 if (event.exploit_team_id, event.victim_team_id, event.service_id) in stealthy_tuples else 1

        try:
            to_return[event.exploit_team_id]["service_attack"][event.service_id].append(score)
        except KeyError:
            to_return[event.exploit_team_id]["service_attack"][event.service_id] = [score]
        assert (isinstance(to_return[event.exploit_team_id]["service_attack"][event.service_id], list))

        to_return[event.exploit_team_id][ScoreType.ATTACK.name] += score

    # Calculate the defensive points
    for (team_id, service_exploitation) in was_team_exploited.items():
        for (service_id, was_exploited) in service_exploitation.items():
            if not service_id in active_normal_service_ids:
                continue
            # Only if this service was exploited do we score defense points
            if service_id in was_service_exploited and was_service_exploited[service_id]:
                if not was_exploited:
                    to_return[team_id][ScoreType.DEFENSE.name] += 1

                    try:
                        to_return[team_id]["service_defense"].append(service_id)
                    except KeyError:
                        to_return[team_id]["service_defense"] = [service_id]
                    assert (isinstance(to_return[team_id]["service_defense"], list))

    for event in koh_ranking_events:
        # Check if the service was active during the tick
        if not event.service.id in active_koh_services_id:
            continue

        ranking = event.koh_rank_results
        ranking.sort(key=lambda rank: rank.rank)
        rank_to_score = {1: 10,
                         2: 6,
                         3: 3,
                         4: 2,
                         5: 1
                         }
        min_num_scored = 5
        current_rank = 1
        previous_score = None
        num_scored = 0
        for rank_result in ranking:
            # nodoby with 0 or less gets any points
            if rank_result.score <= 0:
                break

            # skip over test teams in the koh ranking calculations
            if rank_result.team_id in test_teams:
                continue

            # if this team is at the same point level as the last
            # team, they will be considered the same rank
            if rank_result.score == previous_score:
                assert (event.service_id not in to_return[rank_result.team_id]["koh_points_by_service"])
                to_return[rank_result.team_id]["koh_points_by_service"][event.service.id] = rank_to_score[current_rank]

                to_return[rank_result.team_id][ScoreType.KING_OF_THE_HILL.name] += rank_to_score[current_rank]
                num_scored += 1
                continue

            # have we scored enough people?
            if num_scored >= min_num_scored:
                break
            current_rank = num_scored + 1
            to_return[rank_result.team_id][ScoreType.KING_OF_THE_HILL.name] += rank_to_score[current_rank]
            assert (event.service_id not in to_return[rank_result.team_id]["koh_points_by_service"])
            to_return[rank_result.team_id]["koh_points_by_service"][event.service.id] = rank_to_score[current_rank]
            num_scored += 1
            previous_score = rank_result.score

    # pytype: enable=attribute-error
    # pytype: enable=unsupported-operands

    # do we want to cache that result?
    if is_tick_old_enough_to_cache(tick_id):
        cached = CacheTickScores(score_json=json.dumps(to_return),
                                 tick_id=tick_id)
        db.session.add(cached)
        db.session.commit()

    return dict(tick_id=tick_id,
                teams=to_return,
                )


class ScoreList(Resource):
    """
    Get all the scores for all the ticks.
    """

    def get(self):
        return jsonify([calculate_scores(db, tick.id) for tick in db.session.query(Tick).all()])


class ScoreCTFtimeFormat(Resource):
    """
    Output a JSON of the team scores.
    """

    def get(self):
        scores_all_ticks = [calculate_scores(db, tick.id) for tick in db.session.query(Tick).all()]

        # smoosh the scores together

        smooshed_scores = {}

        for scores in scores_all_ticks:
            team_scores = scores['teams']
            for index in team_scores.keys():
                team_info = team_scores[index]
                team_id = team_info['id']
                attack_score = team_info['ATTACK']
                defense_score = team_info['DEFENSE']
                koh_score = team_info['KING_OF_THE_HILL']
                total_score = attack_score + defense_score + koh_score
                if (team_id not in smooshed_scores.keys()):
                    smooshed_scores[team_id] = 0

                smooshed_scores[team_id] += total_score

        # sort the scores for positions
        sorted_scores = sorted(smooshed_scores.items(), key=lambda x: x[1], reverse=True)

        # format into ctftime JSON format and output
        pos = 0
        ctftime_standings = []
        for score_tuple in sorted_scores:
            pos += 1
            team_id = score_tuple[0]
            score = score_tuple[1]
            team_name = Team.get_team_name(team_id)
            team_standings = {'pos': pos, 'team': team_name, 'score': score}
            ctftime_standings.append(team_standings)

        output_file = "ctftime_scores.json"
        ctftime_json = {"standings": ctftime_standings}

        with open(output_file, 'w') as fp:
            json.dump(ctftime_json, fp, indent=2)
        return jsonify(ctftime_json)


class ScoreInfo(Resource):
    """
    Get the scores for a specific tick.
    """

    def get(self, tick_id):
        return jsonify(calculate_scores(db, tick_id))


class EventList(Resource):
    """
    Get all the events.
    """

    def get(self):
        events = db.session.query(Event).all()
        return jsonify(dict(
            events=[event.to_json() for event in events]
        ))


class TickEvent(Resource):
    """
    Get a single tick's events.
    """

    def get(self, tick_id):
        events = db.session.query(Event).filter_by(tick_id=tick_id).all()
        return jsonify(dict(
            events=[event.to_json() for event in events]
        ))


def create_an_event(event_type: EventType, event_args):
    event = None
    if event_type == EventType.EXPLOIT_SCRIPT:
        event = ExploitScriptEvent(**event_args)
    elif event_type == EventType.SLA_SCRIPT:
        event = SlaScriptEvent(**event_args)
    elif event_type == EventType.SET_FLAG:
        event = SetFlagEvent(**event_args)
    elif event_type == EventType.KOH_SCORE_FETCH:
        event = KohScoreFetchEvent(**event_args)
    elif event_type == EventType.KOH_RANKING:
        ranking = json.loads(event_args['ranking'])
        del event_args['ranking']
        event = KohRankingEvent(**event_args)
        db.session.add(event)
        for rank in ranking:
            result = KohRankResult(koh_ranking_event=event,
                                   **rank)
            db.session.add(result)
    elif event_type == EventType.PCAP_CREATED:
        event = PcapCreatedEvent(**event_args)
    elif event_type == EventType.PCAP_RELEASED:
        event = PcapReleasedEvent(**event_args)
    elif event_type == EventType.STEALTH:
        event = StealthEvent(**event_args)

    return event


class NewEvent(Resource):
    """
    Create a new event.
    """

    def post(self):
        try:
            event_type = EventType[request.form['event_type']]
        except Exception as e:  # changed? (AttributeError vs. KeyError vs. ValueError)
            abort(400, message="invalid event type, must be one of {} -- exception: {}".format(
                " ".join(t.name for t in EventType), e))

        event_args = request.form.to_dict()

        event_args['event_type'] = event_type.value
        event = create_an_event(event_type, event_args)
        if not event:
            abort(400, message="Error, type {} not supported".format(event_type.name))

        db.session.add(event)
        db.session.commit()


class NewTimestampedEvent(Resource):
    """
    Create a new event.
    """

    def post(self):
        try:
            event_type = EventType[request.form['event_type']]
        except Exception as e:  # changed? (AttributeError vs. KeyError vs. ValueError)
            abort(400, message="invalid event type, must be one of {} -- exception: {}".format(
                " ".join(t.name for t in EventType), e))

        if event_type != EventType.STEALTH:
            abort(400, message="Error, I can't handle STEALTH events")

        event_args = request.form.to_dict()

        try:
            timestamp = datetime.datetime.fromtimestamp(float(event_args.pop("timestamp")))
        except (KeyError, ValueError):
            abort(400, message="numeric timestamp must be provided")

        event_args['tick_id'] = Tick.get_tick_at(timestamp).id
        event_args['event_type'] = event_type.value
        event = create_an_event(event_type, event_args)
        if not event:
            abort(400, message="Error, type {} not supported".format(event_type.name))

        db.session.add(event)
        db.session.commit()


class Visualization(Resource):
    """
    All the data that the viz system needs.

    aka the public_game_state() received by players (on a delay)

    We need to return:
    - services (redacted the private information)
    - patch status (not sure how to do that, not going to for now)
    - points per round
    - KoH scores
    - who exploited who
    - ticks: list of all ticks and when they were created
    """

    def get(self):
        started_dumping_at = datetime.datetime.now()

        all_tick_ids = [tick.id for tick in db.session.query(Tick).all()]

        scores = [calculate_scores(db, tick_id) for tick_id in all_tick_ids]

        cleaned_services = [dict(id=s.id,
                                 name=s.name,
                                 description=s.description,
                                 is_active=s.is_active,
                                 type=s.type.name,
                                 are_pcaps_released=s.release_pcaps,
                                 max_bytes=s.max_bytes,
                                 service_indicator=s.service_indicator.name,
                                 active_ticks=[tick_id for tick_id in all_tick_ids if s.was_active(tick_id)])
                            for s in db.session.query(Service).all() if s.is_visible]

        for cs in cleaned_services:
            cs_id = cs['id']

            num_submitted_patches = Service.get_num_submitted_patches_for_id(cs_id)
            cs['num_submitted_patches'] = num_submitted_patches

            num_accepted_patches = Service.get_num_accepted_patches_for_id(cs_id)
            cs['num_accepted_patches'] = num_accepted_patches

            cs_active = db.session.query(IsActive).filter_by(service_id=cs_id).order_by(IsActive.id.desc()).first()
            if cs_active:
                cs['tick_id'] = cs_active.tick_id
                cs['created_on'] = cs_active.created_on

        cleaned_teams = [dict(id=t.id,
                              name=t.name)
                         for t in db.session.query(Team).order_by(Team.id) if not t.is_test_team]

        # tick time
        tick_time = TickTime.get_current_tick_time()
        current_tick = Tick.get_current_tick()
        current_tick_id = -1
        est_time_remaining = -1
        current_tick_created_on = None
        if current_tick:
            current_tick_id = current_tick.id
            delta = datetime.timedelta(seconds=tick_time)
            est_time_done = current_tick.created_on + delta
            est_time_remaining = max(0, (est_time_done - started_dumping_at).total_seconds())
            current_tick_created_on = current_tick.created_on

        # Exploitation Events (who exploited who)

        exploitation_events = []

        flag_stolen_events = db.session.query(FlagStolenEvent).order_by(FlagStolenEvent.id)
        for event in flag_stolen_events:
            exploitation_events.append(dict(id=event.id,
                                            victim_team_id=event.victim_team_id,
                                            exploit_team_id=event.exploit_team_id,
                                            service_id=event.service_id,
                                            tick=event.tick_id,
                                            created_on=event.created_on))

        stealth_exploitation_events = {}

        stealth_events = db.session.query(StealthEvent).order_by(StealthEvent.id)

        for event in stealth_events:

            se_out = dict(id=event.id, src_team_id=event.src_team_id, dst_team_id=event.dst_team_id)
            service_id = int(event.service_id)
            tick_id = int(event.tick_id)
            try:
                stealth_exploitation_events[tick_id][service_id].append(se_out)
            except KeyError:
                if event.tick_id not in stealth_exploitation_events:
                    stealth_exploitation_events[tick_id] = {service_id: [se_out]}
                else:
                    stealth_exploitation_events[tick_id][service_id] = [se_out]

        koh_rankings = []
        # KoH Scoring (including ranking, points, and metadata)
        koh_events = db.session.query(KohRankingEvent)
        koh_real_active = {}
        for koh_event in koh_events:
            if koh_event.service.was_active(koh_event.tick_id):
                koh_rankings.append(dict(service_id=koh_event.service_id,
                                         tick=koh_event.tick_id,
                                         results=[dict(rank=r.rank,
                                                       team_id=r.team_id,
                                                       score=r.score,
                                                       metadata=r.data)
                                                  for r in koh_event.koh_rank_results],
                                         created_on=koh_event.created_on))

        # this is sketchy, we had multiple koh's enabled at the same time,
        # to create which one was active, this uses the largest value
        # this makes "active_ticks" closer to what it should be for subsequent processing
        # active_koh = {}
        # for kohr in sorted(koh_rankings, key=lambda k: k['service_id']):
        #     active_koh[kohr['tick']] = kohr['service_id']
        #
        # for cs in cleaned_services:
        #     if cs['type'] == "KING_OF_THE_HILL":
        #         cs['active_ticks'] = [tick for tick, service_id in active_koh.items() if service_id == cs['id']]
        #         print(f"{cs['id']} {cs['active_ticks']}")

        ticks = [t.to_json() for t in db.session.query(Tick)]
        visualization_json = {'scores': scores,
                              'services': cleaned_services,
                              'teams': cleaned_teams,
                              'current_tick': current_tick_id,
                              'current_tick_created_on': current_tick_created_on,
                              'current_tick_duration': tick_time,
                              'exploitation_events': exploitation_events,
                              'stealth_exploitation_events': stealth_exploitation_events,
                              'est_time_remaining': est_time_remaining,
                              'started_dumping_at': started_dumping_at.isoformat('T'),
                              'koh_rankings': koh_rankings,
                              'ticks': ticks,
                              }

        return jsonify(visualization_json)


def init_test_data(reset_game=False):
    if reset_game:
        meta = db.metadata
        for table in reversed(meta.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()

    real_team_data = \
    yaml.safe_load(open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'team_info.yml'), 'r'))['teams']
    for t in real_team_data:
        _team = Team(**t)
        db.session.merge(_team)

    db.session.commit()

    real_service_data = \
    yaml.safe_load(open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'service_info.yml'), 'r'))['services']
    for s in real_service_data:
        exploit_scripts = []
        sla_scripts = []
        test_scripts = []
        local_interaction_scripts = []
        if s['type'] == "NORMAL":
            s['service_docker'] = "{}:{}".format(s['name'], s['commit'])
            s['interaction_docker'] = "{}-interaction:{}".format(s['name'], s['commit'])
            s['local_interaction_docker'] = "{}-local-tester:{}".format(s['name'], s['commit'])
            s["execution_profile"] = "{}"

            exploit_scripts = s['exploit_scripts']
            del s['exploit_scripts']
            sla_scripts = s['sla_scripts']
            del s['sla_scripts']
            if 'test_scripts' in s:
                test_scripts = s['test_scripts']
                del s['test_scripts']

            if 'local_interaction_scripts' in s:
                local_interaction_scripts = s['local_interaction_scripts']
            if 'local_interaction_scripts' in s:
                del s['local_interaction_scripts']
            assert s['isolation']

        else:
            for unwanted in ['exploit_scripts', 'sla_scripts', 'test_scripts', 'local_interaction_scripts']:
                if unwanted in s:
                    del s[unwanted]

        del s['commit']

        _service = Service(**s)

        _service = db.session.merge(_service)

        db.session.commit()

        db.session.query(ExploitScriptPath).filter_by(service_id=_service.id).delete()
        for e in exploit_scripts:
            exploit_path = ExploitScriptPath(path=e,
                                             service=_service)
            db.session.add(exploit_path)

        db.session.query(SlaScriptPath).filter_by(service_id=_service.id).delete()
        for sla in sla_scripts:
            sla_path = SlaScriptPath(path=sla,
                                     service=_service)
            db.session.add(sla_path)

        db.session.query(TestScriptPath).filter_by(service_id=_service.id).delete()
        for test in test_scripts:
            test_path = TestScriptPath(path=test,
                                       service=_service)
            db.session.add(test_path)

        db.session.query(LocalInteractionScriptPath).filter_by(service_id=_service.id).delete()
        for local in local_interaction_scripts:
            test_local_interaction = LocalInteractionScriptPath(path=local,
                                                                service=_service)
            db.session.add(test_local_interaction)

        db.session.commit()

    # Add initial game state
    if db.session.query(GameState).count() == 0:
        _gs = GameState(state=State.INIT)
        db.session.add(_gs)

    db.session.commit()


# Team endpoints
api.add_resource(TeamList, "/api/v1/teams")
api.add_resource(TeamInfo, "/api/v1/team/<int:team_id>")
api.add_resource(TeamPcapList, "/api/v1/team/<int:team_id>/pcaps")
api.add_resource(TeamFromIP, "/api/v1/team-from-ip/<ip>")

# Service endpoints
api.add_resource(ServiceList, "/api/v1/services")
api.add_resource(ServiceInfo, "/api/v1/service/<int:service_id>")
api.add_resource(ReleaseServicePcaps, "/api/v1/service/<int:service_id>/release_pcaps/<int:value>")
api.add_resource(ServiceIsVisible, "/api/v1/service/<int:service_id>/is_visible/<int:value>")
api.add_resource(ServiceIsActive, "/api/v1/service/<int:service_id>/is_active/<int:value>")
api.add_resource(SetServiceIndicator, "/api/v1/service/<int:service_id>/service_indicator/<value>")
api.add_resource(SetServiceProfile, "/api/v1/service/<int:service_id>/profile")

# Ticket endpoints
api.add_resource(NewTicket, "/api/v1/ticket/<int:team_id>")
api.add_resource(NewTicketStatus, "/api/v1/ticket/status/<int:ticket_id>")
api.add_resource(NewTicketMessage, "/api/v1/ticket/<int:ticket_id>/message")
api.add_resource(TeamMessageAllowed, "/api/v1/ticket/<int:ticket_id>/message/<int:team_id>/team")

api.add_resource(TeamTicketList, "/api/v1/tickets/<int:team_id>")
api.add_resource(TicketList, "/api/v1/tickets")

# Uploaded patch endpoints
api.add_resource(TeamUploadedPatchInfo, "/api/v1/team/<int:team_id>/uploaded_patches")
api.add_resource(UploadPatch, "/api/v1/service/upload_patch")
api.add_resource(NewPatchStatus, "/api/v1/patch/<int:patch_id>/status")
api.add_resource(PatchInfo, "/api/v1/patch/<int:patch_id>")

# Visualization endpoints
api.add_resource(Visualization, "/api/v1/visualization")

# Game event endpoints
api.add_resource(EventList, "/api/v1/events")
api.add_resource(TickEvent, "/api/v1/events/<int:tick_id>")
api.add_resource(NewEvent, "/api/v1/event")
api.add_resource(NewTimestampedEvent, "/api/v1/timestamped_event")

# Score endpoints
api.add_resource(ScoreList, "/api/v1/scores")
api.add_resource(ScoreCTFtimeFormat, "/api/v1/ctftime")
api.add_resource(ScoreInfo, "/api/v1/score/<int:tick_id>")

# Flag endpoints
api.add_resource(GenerateFlag, "/api/v1/flag/generate/<int:service_id>/<int:team_id>")
api.add_resource(GetLatestFlag, "/api/v1/flag/latest/<int:service_id>/<int:team_id>")
api.add_resource(SubmitFlag, "/api/v1/flag/submit/<int:team_id>")
api.add_resource(FlagsForTick, "/api/v1/flags/<int:tick_id>")

# Game state endpoints
api.add_resource(StateOfTheGame, "/api/v1/game/state")
api.add_resource(StartGame, "/api/v1/game/start")

# Tick Control
api.add_resource(NewTick, "/api/v1/tick/next")
api.add_resource(ChangeTickTime, "/api/v1/tick/time")

# Public Game State Controls
api.add_resource(ChangeIsGameStatePublic, "/api/v1/game/is_game_state_public/<int:value>")
api.add_resource(ChangeGameStateDelay, "/api/v1/game/game_state_delay/<int:value>")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="game_store")
    parser.add_argument("--debug", action="store_true", help="Enable debugging")
    parser.add_argument("--profile", action="store_true", help="Enable profiling")
    parser.add_argument("--port", type=int, default=5000, help="Port to listen on [default: 5000]")
    parser.add_argument("--host", default='127.0.0.1', help="Host to listen on [default: 127.0.0.1]")
    parser.add_argument("--test", action="store_true", help="Add test data")
    parser.add_argument("--version", action="version", version="%(prog)s v0.6.2")
    logging.basicConfig()
    args = parser.parse_args()
    if args.test:
        db.create_all()
        init_test_data()
    if args.profile:
        app.config['PROFILE'] = True

        # pytype: disable=wrong-arg-types
        app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[150],
                                          sort_by=('cumulative',))  # type: ignore   # (sort_by's type is tricky)
        # pytype: enable=wrong-arg-types

    app.run(host=args.host, port=args.port, debug=args.debug)

if "FLASK_WSGI_DEBUG" in os.environ:
    from werkzeug.debug import DebuggedApplication

    app.wsgi_app = DebuggedApplication(app.wsgi_app, True)
    app.debug = True

    db.create_all()
    init_test_data()
