# team-interface

Responsible for providing an interface to the teams so that they can
submit flags, get pcaps, upload patches, and get their patch status.
Split into a backend flask REST API, which essentially wraps the
database-api, and a React frontend.

## backend

The [backend](backend) is a Flask REST API that acts as a proxy to the
database-api (so the teams are not given direct access).

### Usage Exapmle

~~~bash
$ python -m ooogame.team_interface.backend.app --debug --dbapi <DB_API_ENDPOINT>
~~~

## frontend

The [frontend](frontend) has its own README, you should go check it out there.
