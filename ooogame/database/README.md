# game_store

This package implements an API for the game data store.

## Structure

[api.py](api.py) has the backend of the database,
[deployment](deployment) has the files necessary for deployment (used
by the dockerfile in [../../dockerfiles](../../dockerfiles),
[client/db.py](client/db.py) has the database client (which is used by
other services/components), and [frontend](frontend) has the React of
the database frontend (for the administrators to use).

## Usage Example

To run the api with test data with debug mode:

~~~bash
$ python -m ooogame.database.api --test --debug
~~~

Test data will be done using sqlite, so you don't need to set up a DB or anything.

To run against a production database and listen on port 1234:

~~~bash
$ SQLALCHEMY_DATABASE_URI=${db_uri} python -m ooogame.database.api --port 1234
~~~

For more information, run `python -m ooogame.database.api --help`.

## Developing `frontend`

The [README](frontend) in the frontend is long, here's the short version:

1. [Install npm](https://www.npmjs.com/get-npm).

2. Install all the npm packages. In the `frontend` directory do:
~~~bash
$ npm install
~~~

3. Run the test database api using the defaults in one terminal:
~~~bash
$ python -m ooogame.database.api --test --debug
~~~

4. Run the amazing (no joke) react dev environment (this will compile the react app, load a web server, auto-watch the react files, rebuild when there's a change, and auto-refresh your browser) by doing this in another terminal from the `frontend` directory:
~~~bash
$ yarn start
~~~

## Migrations

This is kept for legacy reasons. We dont'

`migrations` directory contains the info for the migrations.

~~~bash
$ SQLALCHEMY_DATABASE_URI=${db_uri} flask db migrate
$ SQLALCHEMY_DATABASE_URI=${db_uri} flask db upgrade
~~~

## Deployment

TODO

