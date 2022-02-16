#!/usr/bin/env python3
import argparse
import enum
import logging
import os
import re
import subprocess
import sys
import time
import traceback

import kubernetes

from ..database import Db
from ..flagbot import flagbot

l = logging.getLogger("fresh-flagbot")

def get_services_by_name(the_db):
    services = the_db.services()
    services_by_name = {s['name']: s for s in services}
    return services_by_name

def main(the_db, k8s_api, max_ticks=None):
    l.info("Started up the fresh-flagbot.")

    i = 0
    while True:
        l.info("Going to monitor the k8s cluster to get pod events, to put flags on new running ones.")

        services_by_name = get_services_by_name(the_db)

        watch = kubernetes.watch.Watch()

        for result in watch.stream(k8s_api.list_pod_for_all_namespaces):
            l.debug(repr(result))
            pod_name = result['object'].metadata.name
            pod_namespace = result['object'].metadata.namespace
            status = result['object'].status.phase
            if status != "Running":
                l.info(f"pod {pod_name} is status {status}, skipping")
                continue

            # Check that the container is running
            are_containers_running = all(status.state.running for status in result['object'].status.container_statuses)
            if not are_containers_running:
                l.info(f"containers are not running, skipping")
                l.debug(f"{result['object'].status.container_statuses}")
                continue

            # Example pod name: fake3-team-14-random-gibberish
            l.debug(pod_name)

            # This regex is a bit complicated because it needs to
            # detect both shared and private pod names. The +? means a
            # non-greedy +, so that we only capture to the first result.
            result = re.search('^(.+?)-team-(\d+)(-team-\d+)?', pod_name)
            l.debug(result)
            if not result:
                l.info(f"pod {pod_name} is not a valid game pod, skipping")
                continue

            service_name = result.group(1)
            team_id = result.group(2)

            if not service_name in services_by_name:
                l.error(f"weird, got a service name {service_name} that is not in the list, trying to refresh")
                services_by_name = get_services_by_name(the_db)

            if not service_name in services_by_name:
                l.error(f"pod {pod_name} must not be a team pod")
                continue

            team = the_db.team(team_id)
            if team['is_test_team']:
                l.info(f"Skipping team_id={team_id} because it is a test_team, so they don't need a flag.")
                continue

            service = services_by_name[service_name]
            service_id = service['id']

            if service['type'] != 'NORMAL':
                l.info(f"Skipping service {service_id} because type is {service['type']}")
                continue

            flag = the_db.get_flag(service_id, team_id)
            if not (flag and 'flag' in flag):
                l.error(f"no flag available for service name {service_name} id {service_id} team {team_id}, skipping")
                continue            

            the_flag = flag['flag']

            # Hitting a bug where k8s says that the pod is up, but the container is unavailable and we hit a 500
            # so we're just going to try this multiple times
            # https://github.com/kubernetes-client/python/issues/739
            result = None
            max_attempts = 3
            attempts = 0
            while attempts <= max_attempts:
                try:
                    l.info(f"Try {attempts} to set flag for max time {max_attempts}")
                    result = flagbot.set_flag_pod(the_flag, service['flag_location'], pod_name, pod_namespace, k8s_api)
                except Exception:
                    l.error(f"Error trying to set flag {traceback.format_exc()}")

                if result:
                    break

                attempts += 1

            if not result:
                result = flagbot.FlagResult.FAIL
                l.error(f"Failed to set the flag")

            response = the_db.update_event(event_type="SET_FLAG",
                                           reason=f"Reset flag for new pod for team {team_id} service {service_id}",
                                           team_id=team_id,
                                           service_id=service_id,
                                           flag_id=flag['id'],
                                           result=result.name)
            l.info(f"{result.name} in setting a fresh flag team {team_id} service {service_id}")
            i += 1
            if i == max_ticks:
                l.info(f"Hit the max number of ticks {max_ticks} {i}")
                return

            

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="fresh-flagbot")
    parser.add_argument("--dbapi", help="The location of the database API")
    parser.add_argument("--version", action="version", version="%(prog)s v0.0.2")

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
    main(the_db, k8s_api)
        
    
    
    
