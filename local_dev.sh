#!/bin/sh -e
set -x
VIRTENV=~/.virtualenvs/ooo/bin/activate
VIRTCMD=""
if [ -f $VIRTENV ]; then
    VIRTCMD=". ${VIRTENV}"
    ${VIRTCMD}
    echo "Virtual Environment = ${VIRTUAL_ENV}"
fi
UTC_TZ="export TZ=UTC"  # the db assumes localtimes are UTC, let's have the whole session in UTC

${UTC_TZ}

command -v tmux

SESSION="DClocal"

tmux start-server
if tmux list-sessions|grep $SESSION; then
    tmux kill-session -t $SESSION
fi
# Start the database api
tmux new-session -d -s $SESSION -n database-api -- /bin/bash -c "${UTC_TZ};${VIRTCMD}; SQLALCHEMY_DATABASE_URI=mysql://root@172.17.0.2/ooo DATABASE_API=http://localhost:5000 DOCKER_REGISTRY=localhost:6000/ python -m ooogame.database.api --test --debug;bash"

# Wait for database api to be up
until $(curl --output /dev/null --silent --head --fail http://localhost:5000/api/v1/game/state); do
    printf '.'
    sleep 2
done

# Start the frontend in the same pane
tmux split-window -d -t $SESSION:database-api.0 -c $(pwd)/ooogame/database/frontend "yarn install && yarn start"

# Start the team interface backend
tmux new-window -d -n team-interface -- /bin/bash -c "${UTC_TZ};${VIRTCMD}; python -m ooogame.team_interface.backend.app --debug --dbapi 'http://localhost:5000'"

# Start the frontend in the same pane
tmux split-window -d -t $SESSION:team-interface.0 -c $(pwd)/ooogame/team_interface/frontend "yarn install && yarn start"

# Start the gamebot
tmux new-window -d -n gamebot -- /bin/bash -c "${UTC_TZ};${VIRTCMD}; python -m ooogame.gamebot.gamebot --dbapi 'http://localhost:5000'"

# Start the local docker registry for testing patching
tmux new-window -d -n docker-registry -- docker run --rm -p 6000:5000 registry

# Create a nice ipython session with the db client
tmux new-window -d -n ipython -- /bin/bash -c "${UTC_TZ};${VIRTCMD}; ipython"
tmux select-window -t $SESSION:ipython
tmux send-keys -t $SESSION:ipython "from ooogame.database.client import Db" Enter 'db = Db("http://localhost:5000")' Enter

tmux select-window -t $SESSION:database-api.0
tmux attach-session -t $SESSION
