#!/usr/bin/env python3
import argparse
import datetime
import enum
import json
import logging
import multiprocessing
import os
import subprocess
import sys
import threading
import time

import kubernetes

from ..database import Db

l = logging.getLogger("flagbot")

class FlagResult(enum.Enum):
    SUCCESS = enum.auto()
    FAIL = enum.auto()

def set_flag_pod(new_flag, flag_location, pod_name, pod_namespace, k8s_api):
    # set the flag
    sh_command = f"cat - > '{flag_location}'"

    drop_flag_command = ["/bin/sh", "-c", sh_command]

    l.info(f"Setting flag {flag_location} in pod {pod_name} namespace {pod_namespace} with {drop_flag_command}")
    try:
        resp = kubernetes.stream.stream(k8s_api.connect_get_namespaced_pod_exec,
                                        pod_name,
                                        pod_namespace,
                                        command=drop_flag_command,
                                        stdin=True,
                                        stderr=True,
                                        stdout=True,
                                        tty=False,
                                        _preload_content=False,
        )
        resp.write_stdin(new_flag)
        resp.close()
    except Exception as e:
        estr = str(e).replace('\n', ' ')
        l.error(f"could not set flag exception_type={type(e)} exception={estr}")
        return FlagResult.FAIL

    return FlagResult.SUCCESS


def set_flag_deployment(new_flag, flag_location, deployment_name, team, service, k8s_api):
    error = False
    l.info(f"Going to set flag={new_flag} for team_id={team['id']} team_name={team['name']} service_id={service['id']}")

    # get all pods in deployment
    ret = k8s_api.list_pod_for_all_namespaces(label_selector=f"app={deployment_name}")
    l.info(f"{deployment_name} has {len(ret.items)} pods")

    num_fail = 0
    for i in ret.items:
        pod_name = i.metadata.name
        pod_namespace = i.metadata.namespace
        l.info(f"Processing pod pod_name={pod_name}")
        if i.status.phase != 'Running':
            l.info(f"Skipping pod_name={pod_name} because it's state={i.status.phase} is not Running")
            continue
        if i.metadata.deletion_timestamp:
            l.info(f"Skipping pod_name={pod_name} because it's being deleted")
            continue

        response = set_flag_pod(new_flag, flag_location, pod_name, pod_namespace, k8s_api)
        if response != FlagResult.SUCCESS:
            team_name = json.dumps(team['name'])
            service_name = json.dumps(service['name'])
            l.error(f"Did not set flag for pod_name={pod_name} team_id={team['id']} team_name={team_name} service_name={service_name} service_id={service['id']}")
            num_fail += 1

    if num_fail == 0:
        return FlagResult.SUCCESS
    elif num_fail == len(ret.items):
        l.error(f"failed to set all flags for team_id={team['id']}")
        return FlagResult.FAIL
    else:
        l.error(f"set some flags for team_id={team['id']} num_pods={len(ret.items)} num_fail={num_fail}")
        return FlagResult.FAIL

def create_flags_for_team(the_db, k8s_api, team, teams, ad_services):
    for service in ad_services:
        flag = the_db.generate_flag(service['id'], team['id'])
        if service['central_server']:
            deployment_name = service['central_server']
            flag_location = f"{service['flag_location']}/team-{team['id']}"
        else:
            deployment_name = f"{service['name']}-team-{team['id']}"
            flag_location = service['flag_location']

        if service['isolation'] == "SHARED":
            result = set_flag_deployment(flag['flag'], flag_location, deployment_name, team, service, k8s_api)
        elif service['isolation'] == "PRIVATE":
            has_failed = False
            l.info(f"Setting a bunch of flags for a private (team-team hosting) service")
            for other_team in teams:
                src_team_deployment_name = f"{deployment_name}-team-{other_team['id']}"
                l.info(f"Attempting to set flag to {src_team_deployment_name}")
                result = set_flag_deployment(flag['flag'], flag_location, src_team_deployment_name, team, service, k8s_api)
                if result == FlagResult.FAIL:
                    has_failed = True
            if has_failed:
                result = FlagResult.FAIL
        else:
            assert False, "Should never get here"

        if result == FlagResult.FAIL:
            l.error(f"Failed set flag for team {team['id']} service {service['id']} result {result.name}")
        else:
            l.info(f"Set flag for team {team['id']} service {service['id']} result {result.name}")

        response = the_db.update_event(event_type="SET_FLAG",
                                       reason=f"Set flag for team {team['id']} service {service['id']}",
                                       team_id=team['id'],
                                       service_id=service['id'],
                                       flag_id=flag['id'],
                                       result=result.name)

def main(the_db, k8s_api, max_ticks=None, wait=True, concurrency=True, concurrency_lib='multiprocessing'):
    l.info("Started up the flagbot.")

    i = 0
    while True:
        if wait:
            l.info("Waiting for the next tick.")
            the_db.wait_until_new_tick()
        gamestate = the_db.game_state()
        tick = gamestate['tick']
        l.info("Got that new tick, let's set the flags.")

        teams = the_db.teams()
        services = the_db.services()
        ad_services = [ s for s in services if s['type'] == 'NORMAL' ]

        # For every team, for every service, generate a flag and set it
        before = datetime.datetime.now()
        jobs = []
        if concurrency_lib == 'multiprocessing':
            lib = multiprocessing.Process
        elif concurrency_lib == 'threading':
            lib = threading.Thread
        else:
            assert False
        for team in teams:
            j = lib(target=create_flags_for_team, args=(the_db, k8s_api, team, teams, ad_services))
            j.start()
            jobs.append(j)
            if not concurrency:
                j.join()

        for j in jobs:
            j.join()
        after = datetime.datetime.now()
        diff = after - before

        l.info(f"flagbot completed processing of num_services={len(ad_services)} services for tick tick={tick} in time={diff.total_seconds()} seconds")

        i += 1
        if i == max_ticks:
            l.info(f"Hit the max number of ticks {max_ticks} {i}")
            return




if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="flagbot")
    parser.add_argument("--dbapi", help="The location of the database API")
    parser.add_argument("--version", action="version", version="%(prog)s v0.2.0")
    parser.add_argument("--no-loop", action="store_true", help="Run once and exit, rather than looping.")
    parser.add_argument("--no-wait", action="store_true", help="Don't wait for a new tick.")

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

    the_db = Db(database_api)

    kubernetes.config.load_kube_config()
    k8s_api = kubernetes.client.CoreV1Api()
    main(the_db, k8s_api, max_ticks=1 if args.no_loop else None, wait=not args.no_wait)
