# patchbot

The patchbot is responsible for testing the patches submitted by the teams.

Instead of the patchbot polling for jobs, we are using RQ (Redis Queue) https://github.com/rq/rq for the database to put a job, which involves calling the `test_patch` function of the patchbot.

The patchbot exposes functionality to test/run patches locally, so we have added visability in what is going on. 

## Usage Example

~~~bash
$ python -m ooogame.patchbot.patchbot --patch-id <patch-id-to-test>
~~~

Where `<patch-id-to-test>` is the patch ID to test, and it will use the current production defaults for docker registry (used to fetch the base service image, the remote interaction image, and the local image) and the database. This is safe because it will not update the DB or the docker registry (i.e., everything is a read operation).

You can also specify:

- `--dbapi` to specify the location of the database api (in case you want to test locally).
- `--registry` to specify the location of a docker registry to use (if you want to test locally). Note that this registry must have the proper images for the service that you're testing. 

