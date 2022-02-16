# dcf-game-infrastructure

[![](https://github.com/o-o-overflow/dcf-game-infrastructure/workflows/Test/badge.svg)](https://github.com/o-o-overflow/dcf-game-infrastructure/actions)

All the components necessary to run a game of the OOO DC CTF finals.

Authors: [adamd](https://adamdoupe.com), [hacopo](https://jacopo.cc), [Erik Trickel](https://trickel.com/), [Zardus](https://www.yancomm.net/), and [bboe](https://bryceboe.com/)

## Design Philosophy

This repo contains all the game components necessary to run an Attack-Defense CTF that OOO used from 2018--2021.

The design is based on adamd's experience building the [ictf-framework](https://github.com/shellphish/ictf-framework).

There are fundamental tenenats that we try to follow in the design of the system:

### Spoke component model

The communication design of the components in the system (which you can kind of think of as micro-services) is a "spoke" model, where every component talks to the database (through a RESTish API), and no component directly talks to any other.

In this way, each component can be updated separately and can also be _scaled_ independently using our k8s hosting.

This also made testing of each component easier, as the only dependence on a component is on the state of the database.

The only exception to this is the `patchbot` (the component that needs to test the patches submitted by the teams).

The database API puts the `patchbot` testing jobs into an [RQ (Redis Queue)](https://python-rq.org), which all the `patchbot` workers pull jobs from.

### Append-only database design

Fundamentally, a CTF database needs to calculate scores (that's essentially what the teams care about).

Prior design approaches that we've used would have a `points` or `score` column in the `team` table, and when they acquired or lost points, the app code would change this value.

However, many crazy things can happen during a CTF: recalculating scores or missed flags, even changing the scoring functions itself.

These can be difficult to handle depending on how the system is developed.

Therefore, we created a completely append-only database model, where no data in the DB is ever deleted or changed.

Even things like `service` status (the GOOD, OK, LOW, BAD that we used) is not a column in the `services` table.
Every change of status would created a new `StatusIndicator` row, and the `services` would pull the latest version from this table.

### Event model

Related to the append-only database design, everything in the database was represented by events.

The database would store all game events (in our game over the years was `SLA_SCRIPT`, `FLAG_STOLEN`, `SET_FLAG`, `KOH_SCORE_FETCH`, `KOH_RANKING`, `PCAP_CREATED`, `PCAP_RELEASED`, and `STEALTH`).

Then, the state of the game is based on these events.

An additional benefit is that these events could be shipped to the teams as part of the `game_state.json`.

### Separate k8s clusters

How we ran this is with _two_ [k8s](https://kubernetes.io) clusters: an admin cluster and a game cluster.

The `admin` cluster ran all of these components.

The `game` cluster ran all of the CTF challenges.

We used this design to do things like drop flags on the services.
The `flagbot` used `kubectl` to drop a flag onto a service running in the other cluster.

This also allowed us to lock down the `game` cluster so that the vulnerable services couldn't make external requests, could be scaled separately, etc.


## Install Requirements

This package is pip installable, and installs all dependencies. Do the following in a virtualenv:

~~~bash
$ pip install -e .
~~~

**NOTE:** If you want to connect to a mysql server (such as in prod or when deving against a mysql server), install the `mysqlclient` dependency like so:

~~~bash
$ pip install -e .[mysql]
~~~

## Testing

Make sure the tests pass before you commit, and add new test cases in [test](test) for new features.

Note the database API now checks that the timezone is in UTC, so you'll need to specify that to run the tests:

~~~bash
$ TZ=UTC nosetests -v
~~~

## Local Dev

If you're using tmux, I created a script [local_dev.sh](local_dev.sh)
that will run a database-api, database-api frontend, team-interface
backend, team-interface frontend, gamebot, and an ipython session with
a database client created.

Just run the following

~~~bash
$ ./local_dev.sh
~~~

## Deploy to prod

Build and `-p` push the image to production registry.

~~~bash
$ ./deploy.sh -p
~~~

Won't `-r` restart the running services, need to do:

~~~bash
$ ./deploy.sh -p -r
~~~


## database-api

This has the tables for the database, a REST API to access it, and a python client to access the REST API.

See [ooogame/database](ooogame/database) for details.

## flagbot

Responsible for putting new flags into all the services for every game tick.

See [ooogame/flagbot](ooogame/flagbot) for details.


## fresh-flagbot

Responsible for putting a new flags into a pod when it first comes up (from a team patching the service).

See [ooogame/fresh_flagbot](ooogame/fresh_flagbot) for details.

## gamebot

Responsible for incrementing the game's ticks.

See [ooogame/gamebot](ooogame/gamebot) for details.

## koh-scorebot

Responsible for extracting the King of the Hill (koh) scores from all
the koh pods every tick, and submitting them to the database.

See [ooogame/koh_scorebot](ooogame/koh_scorebot) for details.

## team-interface

Responsible for providing an interface to the teams so that they can
submit flags, get pcaps, upload patches, and get their patch status.
Split into a backend flask REST API, which essentially wraps the
database-api, and a React frontend.

See [ooogame/team_interface](ooogame/team_interface) for details.

## pcapbot

Responsible for picking up all the newly generated pcaps, anonymize
them, and if the service is releasing pcaps then release them.

See [ooogame/pcapbot](ooogame/pcapbot) for details.

## gamestatebot

Responsible for creating the game state at every new tick and storing them in the nfs, and release them publicly.

See [ooogame/gamestatebot](ooogame/gamestatebot) for details.

**This is also the component that pushes data to the public scoreboard**
