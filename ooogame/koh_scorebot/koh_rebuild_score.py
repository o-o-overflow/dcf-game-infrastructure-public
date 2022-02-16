#!/usr/bin/env python3
import argparse
import collections
import enum
import json
import logging
import os
import subprocess
import sys
import time

import kubernetes

from ..database import api
from ..database import Db

l = logging.getLogger("koh-rebuild-scorebot")

SERVICE_ID = 11


if __name__ == "__main__":
    l.info("Started up the koh-score-adjuster!!!.")
    l.info("This will ensure that the scores for pinboooll are only monotically increasing")

    last_score = collections.defaultdict(lambda: (0, None))

    events = api.db.session.query(api.KohRankingEvent).filter_by(service_id=SERVICE_ID).order_by(api.KohRankingEvent.tick_id.asc())
    for e in events:
        l.info(f"Fixing tick_id={e.tick_id} id={e.id} service_id={e.service_id}")
        
        correct_results = []

        # Go and get the current results for this tick
        for r in e.koh_rank_results:
            team_id = r.team_id
            rank = r.rank
            score = r.score
            data = r.data

            prior_score, prior_data  = last_score[team_id]

            if prior_score > score:
                l.info(f"Fixing score for tick={e.tick_id} id={r.id} team_id={team_id} wrong_score={score} prior_score={prior_score}")
                score = prior_score
                data = prior_data
            elif score > prior_score:
                last_score[team_id] = (score, data)

            correct_results.append((score, data, team_id, r))

        correct_results.sort(reverse=True)
        l.info(f"Correct results for tick_id={e.tick_id} correct_results={correct_results}")

        rank = 1
        for score, data, team_id, result in correct_results:
            result.score = score
            result.data = data
            result.rank = rank

            api.db.session.merge(result)
            rank += 1
        api.db.session.commit()


    # Check that this actually worked right

    tick_team_scores = dict()
    events = api.db.session.query(api.KohRankingEvent).filter_by(service_id=SERVICE_ID).order_by(api.KohRankingEvent.tick_id.asc())
    for e in events:
        tick_team_scores[e.id] = dict()
        for r in e.koh_rank_results:
            tick_team_scores[e.id][r.team_id] = r.score

    for team_id in range(1, 17):
        prior_score = 0
        for tick_id, team_scores in tick_team_scores.items():
            team_score = team_scores[team_id]
            if team_score < prior_score:
                import ipdb; ipdb.set_trace()
            prior_score = team_score
