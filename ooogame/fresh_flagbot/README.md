# fresh-flagbot

Listens to the game k8s cluster, and when there's a new pod it sets the current flag for that team/service.

This is necessary because when teams patch services, a new pod spins up, and the flag would be stale/invalid.

## Usage Example

~~~bash
$ python -m ooogame.fresh_flagbot.fresh_flagbot --dbapi <DB_API_ENDPOINT>
~~~

where `<DB_API_ENDPOINT>` is running the database-api, something like `http://localhost:5000`

As the fresh_flagbot drops flags in the game k8s cluster, you'll need to be able to access that cluster.

If that's not the default k8s cluster that you access, then you can
set the `KUBECONFIG` environment variable:

~~~bash
$ KUBECONFIG=/path/to/game.k8s.config python -m ooogame.fresh_flagbot.fresh_flagbot --dbapi <DB_API_ENDPOINT>
~~~


