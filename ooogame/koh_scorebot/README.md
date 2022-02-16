# koh-scorebot

Responsible for extracting the King of the Hill (koh) scores from all
the koh pods every tick, and submitting them to the database.

Important to note that the files in the k8s game cluster are
potentially untrusted, so we need to do this carefully.

## koh score format

Every koh service has a `score_location` attribute, this is used to extract the scores.

The first `500` bytes of the file are extracted, using the k8s api.

Then, the file is split on `'\n'`, and the first is interpreted as the
score (max of 999999999), and the second line is metadata that is sent
to the teams.

So, something like this in `score_location` `/score`:

```
100
foobar
```

would be parsed by the koh-scorebot as score: `100`, and metadata: `foobar`.

All this information is extracted, rankings are calculated, and sent
to the database api (which will later calculate the actual scores
based on the rank).

## Usage Example

~~~bash
$ python -m ooogame.koh_scorebot.koh_scorebot --dbapi <DB_API_ENDPOINT>
~~~

where `<DB_API_ENDPOINT>` is running the database-api, something like `http://localhost:5000`

As the koh-scorebot reads files from the game k8s cluster, you'll need to be able to access that cluster.

If that's not the default k8s cluster that you access, then you can
set the `KUBECONFIG` environment variable:

~~~bash
$ KUBECONFIG=/path/to/game.k8s.config python -m ooogame.koh_scorebot.koh_scorebot --dbapi <DB_API_ENDPOINT>
~~~



