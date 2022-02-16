# pcapbot

Responsible for picking up all the newly generated pcaps, anonymize
them, and if the service is releasing pcaps then release them.

## Usage Example

~~~bash
$ python -m ooogame.pcapbot.pcapbot --dbapi <DB_API_ENDPOINT>
~~~

where `<DB_API_ENDPOINT>` is running the database-api, something like `http://localhost:5000`

The `pcapbot` watches a certain directory for new pcaps, which default to `/pcap` and you can specify with `--pcap-dir`.

Another handy option is `--verify-dirs`, which will create the directory structure necessary which is:

~~~
- <pcap-dir>/<service_id>/<team_id>/new : where newly created pcaps are stored
- <pcap-dir>/<service_id>/<team_id>/old : where raw pcaps are stored
- <pcap-dir>/<service_id>/<team_id>/processed : where anonymous pcaps are stored
- <pcap-dir>/<service_id>/<team_id>/released : where anonymous pcaps are released, if the service is releasing pcaps
~~~

