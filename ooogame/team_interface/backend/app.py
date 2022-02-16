#!/usr/bin/env python3
"""
Team Interface Backend API.
"""
import argparse
import functools
import logging
import os
import requests
import sys
import urllib

from flask import Flask, jsonify, request
from flask_restful import Api, Resource, abort, reqparse

from ...database import Db

l = logging.getLogger("team-interface-backend")

app = Flask(__name__)
api = Api(app)

db = None

SERVICES_ENDPOINT = "/api/v1/services"

def require_team_id_from_ip(view_function):
    """
    Function decorator to get the team ID from the ip address. Passes
    the team_id to the team_id parameter in the view_function.
    """
    @functools.wraps(view_function)
    def decorated_function(*args, **kwargs):
        header_team_id = request.headers.get('TEAM-ID')
        if not header_team_id:
            l.error(f"request.headers.get {request.headers.get('TEAM-ID')} not set")
            if app.debug:
                header_team_id = "17"
            else:
                abort(400, message=f"Error, team-id not set")
        try:
            team_id = int(header_team_id)
        except ValueError as e:
            l.error(f"Invalid team-id header {header_team_id}")
            if app.debug:
                team_id = 17
            else:
                abort(400, message=f"Invalid team-id")
        kwargs['team_id'] = team_id
        return view_function(*args, **kwargs)
    return decorated_function


class TeamInfo(Resource):
    """
    Get all the team info that they need.
    """

    method_decorators = [require_team_id_from_ip]

    def get(self, team_id):
        team = db.team(team_id)
        return jsonify(id=team['id'],
                       name=team['name'])

class ServicesInfo(Resource):
    """
    Get the information on all available services.
    """

    method_decorators = [require_team_id_from_ip]

    def get(self, team_id):
        services = db.services()
        to_return = []
        for s in services:
            if not s['is_visible']:
                continue
            service_info = dict(name=s['name'],
                                id=s['id'],
                                description=s['description'],
                                port=s['port'],
                                type=s['type'],
                                team_ip=f"10.13.37.{team_id}",
                                is_active=s['is_active'],
                                are_pcaps_released=s['release_pcaps'],
                                service_indicator=s['service_indicator'],
            )

            to_return.append(service_info)

        return jsonify(services=to_return)

class PatchesInfo(Resource):
    """
    Get all the patches
    """

    method_decorators = [require_team_id_from_ip]

    def get(self, team_id):
        patches = db.team_patches(team_id)['patches']
        patches.sort(key=lambda p: p['id'], reverse=True)

        # sanitize the results from private data
        for p in patches:
            for r in p['results']:
                del r['private_metadata']
        return jsonify(patches)

class PcapInfo(Resource):
    """
    Get all the pcaps for the team
    """

    method_decorators = [require_team_id_from_ip]

    def get(self, team_id):
        pcaps = db.team_pcaps(team_id)
        return jsonify([dict(service_id=p['service_id'],
                             pcap_location="/pcap/{}/released/{}".format(p['service_id'], p['pcap_name']),
                             created_on=p['created_on'])
                        for p in pcaps])

class FlagSubmission(Resource):
    """
    Submit a flag.
    """

    method_decorators = [require_team_id_from_ip]

    def post(self, flag, team_id):
        result = db.submit_flag(team_id, flag)
        if not 'result' in result:
            abort(400, message=result['message'])
        return jsonify(message=result['result'])

class UploadPatch(Resource):
    """
    Upload a patch.
    """

    method_decorators = [require_team_id_from_ip]

    def post(self, team_id):
        service_id = request.form.get('service_id')
        file = request.files.get('file')
        if not service_id or not file:
            abort(400, message='bad request')
        assert file
        response = db.upload_patch(team_id, service_id, file.read())
        return jsonify(message=response['message'])

class TicketList(Resource):
    """
    List the team's tickets
    """
    method_decorators = [require_team_id_from_ip]

    def get(self, team_id):
        tickets = db.tickets(team_id)['tickets']
        return jsonify(tickets=tickets)


class NewTicket(Resource):
    """
    Create a new ticket
    """
    method_decorators = [require_team_id_from_ip]

    def post(self, team_id):
        subject = request.form.get('subject')
        description = request.form.get('description')
        message = db.new_ticket(team_id, subject, description)['message']
        return jsonify(message=message)


class NewTicketMessage(Resource):
    """
    Create a New message for the ticket
    """
    method_decorators = [require_team_id_from_ip]

    def post(self, team_id, ticket_id):
        message_text = request.form.get('message_text')
        message = db.new_ticket_message(team_id,ticket_id, message_text)['message']

        return jsonify(message=message)


# endpoints
api.add_resource(TeamInfo, "/api/team_info")
api.add_resource(PcapInfo, "/api/pcap_info")
api.add_resource(PatchesInfo, "/api/patches_info")
api.add_resource(ServicesInfo, "/api/services_info")
api.add_resource(FlagSubmission, "/api/submit_flag/<flag>")
api.add_resource(UploadPatch, "/api/submit_patch/")

api.add_resource(TicketList, "/api/tickets")
api.add_resource(NewTicket, "/api/ticket")
api.add_resource(NewTicketMessage, "/api/ticket/<int:ticket_id>/message")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="team-interface-backend")
    parser.add_argument("--debug", action="store_true", help="Enable debugging")
    parser.add_argument("--port", type=int, default=5001, help="Port to listen on [default: 5001]")
    parser.add_argument("--host", default='127.0.0.1', help="Host to listen on [default: 127.0.0.1]")
    parser.add_argument("--version", action="version", version="%(prog)s v0.2.0")
    parser.add_argument("--dbapi", help="The location of the database API")

    args = parser.parse_args()
    database_api = None
    if args.dbapi:
        database_api = args.dbapi
    elif 'DATABASE_API' in os.environ:
        database_api = os.environ['DATABASE_API']

    if not database_api:
        l.error("Error, must specify a database api")
        parser.print_help()
        sys.exit(1)

    db = Db(database_api)
    app.run(host=args.host, port=args.port, debug=args.debug)

if 'DATABASE_API' in os.environ:    
    database_api = os.environ['DATABASE_API']
    l.info(f"Setting DB API to {database_api}")
    db = Db(database_api)

if "FLASK_WSGI_DEBUG" in os.environ:
    from werkzeug.debug import DebuggedApplication
    app.wsgi_app = DebuggedApplication(app.wsgi_app, True)
    app.debug = True
    l.setLevel(logging.DEBUG)
