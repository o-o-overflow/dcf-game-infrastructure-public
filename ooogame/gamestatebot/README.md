# gamestatebot

Responsible for creating the game state JSONs at every new tick and storing them. Then, if we are releasing the game state publically, put it in the released dir.

Game state JSON == `public_game_state()` == visualization API endpoint


## Usage Example

~~~bash
$ python -m ooogame.gamestatebot.gamestatebot --dbapi <DB_API_ENDPOINT> --game-state-dir /game_state
~~~

where `<DB_API_ENDPOINT>` is running the database-api, something like `http://localhost:5000`

The `gamestatebot` will store game states in a certain directory pcaps, which you can specify with `--game-state-dir`.

Another handy option is `--create-game-state-dir`, which will create the directory structure necessary which is:

~~~
- <game-state-dir>/game_states : where game_states are stored
- <game-state-dir>/released/game_state.json : where the latest game state is stored
~~~


## Pushing data to the public scoreboard

If `UPLOAD_SCOREBOARD=1` and `~/scoreboard_upload.ppk` is present, it game state JSONs will be pushed to the public scoreboard.

Uploaded files are direcly available at https://a.scoreboard.ooo/d/
