# flagbot

Flagbot is responsible for putting new flags into all the services for every game tick.

## Usage Example

~~~bash
$ python -m ooogame.flagbot.flagbot --dbapi <DB_API_ENDPOINT>
~~~

where `<DB_API_ENDPOINT>` is running the database-api, something like `http://localhost:5000`

As the flagbot drops flags in the game k8s cluster, you'll need to be able to access that cluster.

If that's not the default k8s cluster that you access, then you can
set the `KUBECONFIG` environment variable:

~~~bash
$ KUBECONFIG=/path/to/game.k8s.config python -m ooogame.flagbot.flagbot --dbapi <DB_API_ENDPOINT>
~~~

