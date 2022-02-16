#!/usr/bin/env python3
import argparse
import enum
import logging
import json
import os
import subprocess
import sys
import time

import kubernetes

from ..database import Db

l = logging.getLogger("koh-scorebot")

MAX_KOH_SCORE = 9999999999999

def get_koh_score_from_pod(pod_name, pod_namespace, score_location, k8s_api):
    # get the first 500 bytes of the score file
    get_koh_score_command = ["head", "-c", "500", score_location]
    result = None
    num_failures = 0
    while num_failures < 3:
        try:
            l.info(f"Getting score from pod={pod_name} namespace={pod_namespace} with command={get_koh_score_command} num_failures={num_failures}")
            result = kubernetes.stream.stream(k8s_api.connect_get_namespaced_pod_exec,
                                              pod_name,
                                              pod_namespace,
                                              command=get_koh_score_command,
                                              stdin=False,
                                              stderr=False,
                                              stdout=True,
                                              tty=False,
            )
            break
        except:
            num_failures += 1
            l.error(f"could not get score from pods={pod_name} in namespace={pod_namespace} with command={get_koh_score_command} num_failures={num_failures} exception={sys.exc_info()[1]}")
    return result


def get_score(team, service, score_location, k8s_api, the_db):
    error = False
    score = None
    metadata = None

    l.info("Going to get the score for team {} {} service {}".format(team['id'], team['name'], service['id']))

    if service['central_server']:
        deployment_name = service['central_server']
        score_location = f"{score_location}/team-{team['id']}"
    else:
        deployment_name = f"{service['name']}-team-{team['id']}"

    ret = None
    num_failures = 0
    while num_failures < 3:
        try:
            l.info(f"Going to get the list of pods for app={deployment_name}")
            ret = k8s_api.list_pod_for_all_namespaces(label_selector=f"app={deployment_name}", timeout_seconds=60)
            break
        except Exception:
            num_failures += 1
            l.error(f"could not get list of pods in namespace for app={deployment_name} num_failures={num_failures} exception={sys.exc_info()[1]}")

    if not ret:
        l.error(f"could not fetch the list of pods after num_failures={num_failures} for team_id={team['id']} service_id={service['id']}, score is zero")
        the_db.update_event(event_type="KOH_SCORE_FETCH",
                            reason="Failed to fetch data, weird number of pods.",
                            team_id=team['id'],
                            service_id=service['id'],
                            score=0,
                            data=None,
                            result="FAIL")
        return 0, None


    l.info(f"{deployment_name} has {len(ret.items)} pods")

    if len(ret.items) != 1:
        l.error(f"Weird number of pods {len(ret.items)} for team_id={team['id']} service_id={service['id']}, score is zero")
        the_db.update_event(event_type="KOH_SCORE_FETCH",
                            reason="Failed to fetch data, weird number of pods.",
                            team_id=team['id'],
                            service_id=service['id'],
                            score=0,
                            data=None,
                            result="FAIL")
        return 0, None

    for i in ret.items:
        pod_name = i.metadata.name
        pod_namespace = i.metadata.namespace

        result = get_koh_score_from_pod(pod_name, pod_namespace, score_location, k8s_api)

        score = None
        error = False
        if result == None:
            error = True
            l.error(f"Getting score from {score_location} on team_id={team['id']} service_id={service['id']} pod_name={pod_name}")
        elif result == "":
            l.info(f"Got an empty scorefile from score_location={score_location} on team_id={team['id']} service_id={service['id']} pod_name={pod_name}")
            score = 0
            metadata = None
        else:
            # Be paranoid, they can control the content of this file
            try:
                score_file_content = result.split('\n', maxsplit=1)
                l.debug(f"score file content {score_file_content}")
                if len(score_file_content) > 0:
                    try:
                        score = int(score_file_content[0], base=10)
                        score = min(score, MAX_KOH_SCORE)
                    except ValueError as e:
                        score = 0
                else:
                    score = 0
                if len(score_file_content) > 1:
                    metadata = score_file_content[1]
            except Exception:
                error = True
                l.error(f"parsing score from {score_location} on team {team['id']} service {service['id']} pod {pod_name} error {sys.exc_info()[0]}")

    if error:
        result = "FAIL"
    else:
        result = "SUCCESS"
    the_db.update_event(event_type="KOH_SCORE_FETCH",
                        reason=f"{result} to extract score",
                        team_id=team['id'],
                        service_id=service['id'],
                        score=score,
                        data=metadata,
                        result=result)
    if not score:
        score = 0

    return score, metadata


def main(the_db, k8s_api, max_ticks=None):
    l.info("Started up the koh-scorebot.")

    i = 0
    while True:
        old_tick = the_db.wait_until_new_tick()
        l.info("Got that new tick, get scores from all the koh services.")

        if not old_tick:
            l.info(f"Last tick was {old_tick}, so we don't score")
            continue

        teams = the_db.teams()
        services = the_db.services()
        koh_services = [ s for s in services if s['type'] == 'KING_OF_THE_HILL' ]

        for service in koh_services:
            team_results = []
            for team in teams:
                score_location = service['score_location']

                # extract the score from the score location
                score, metadata = get_score(team, service, score_location, k8s_api, the_db)
                team_results.append(dict(score=score,
                                         data=metadata,
                                         team_id=team['id']))
            l.info(f"Fetched all the scores for service {service['id']}")

            # Now that we have the scores for everyone, compute the list and create the KoH scoring event.
            team_results.sort(key=lambda result: (result['score'], result['team_id']), reverse=True)

            rank = 1
            for result in team_results:
                result['rank'] = rank
                rank += 1

            l.info(f"Ranked all the teams for service {service['id']}: {team_results}")

            json_rankings = json.dumps(team_results)
            l.debug(f"json rankings {json_rankings}")
            # We are scoring the last tick, so we use the old tick id for the event
            response = the_db.update_event(event_type="KOH_RANKING",
                                           reason=f"Ranking of teams for service {service['id']} tick {old_tick}.",
                                           tick_id=old_tick,
                                           ranking=json_rankings,
                                           service_id=service['id'])
            l.info(f"Updated the DB with service {service['id']} team rankings: response code: {response}")

        l.info(f"koh-scorebot completed processing of num_services={len(koh_services)} services for tick old_tick={old_tick}")

        i += 1
        if i == max_ticks:
            l.info(f"Hit the max number of ticks {max_ticks} {i}")
            return




if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="koh-scorebot")
    parser.add_argument("--dbapi", help="The location of the database API")
    parser.add_argument("--version", action="version", version="%(prog)s v0.0.1")

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
