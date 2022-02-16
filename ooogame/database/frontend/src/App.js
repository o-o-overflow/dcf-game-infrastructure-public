import React, {Component} from 'react';
import logo from './logo.svg';
import './App.css';

class App extends Component {
    constructor(props) {
        super(props);
        this.state = {
            state: "",
            tick: "",
            tick_time_seconds: "",
            estimated_tick_time_remaining: 10,
			is_game_state_public: false,
			game_state_delay: -1,
            intervalId: -1,
            countdownId: -1,
            services: [],
            announcements: [],
            teams: [],
            scores: [],
        };
    }

    componentDidMount() {
        document.title = "ADMIN";
        this.updateAtStart();
        const intervalId = setInterval(() => this.updateFrequently(), 5000);
        const countdownId = setInterval(() => this.countdown(), 1000);
        this.setState({
            intervalId: intervalId,
            countdownId: countdownId,
        });

    }

    countdown() {
        if (this.state.estimated_tick_time_remaining != null) {
            var remainingTime = parseInt(this.state.estimated_tick_time_remaining - 1);
            if (remainingTime <= 0) {
                remainingTime = 0;
                this.loadGameStateData();
            }
            this.setState({estimated_tick_time_remaining: remainingTime});
        }
    }

    componentWillUnmount() {
        clearInterval(this.state.intervalId);
    }

    updateAtStart() {
        this.loadGameStateData();
        this.loadServices();
        this.loadTeams();
//        this.loadScores();
//        this.loadAnnouncements();

    }

    updateFrequently() {
        this.loadGameStateData();
        this.loadServices();
//        this.loadScores();

//        this.loadAnnouncements();
    }

    loadGameStateData() {
        fetch('/api/v1/game/state', {method: 'GET',})
            .then(response => response.json().then(body => ({body, status: response.status})))
            .then(({body, status}) => {
                if (status !== 200) {
                    console.log(status);
                    console.log(body.message);
                    return;
                }
                this.setState({
                    state: body.state,
                    tick: body.tick,
                    tick_time_seconds: body.tick_time_seconds,
					is_game_state_public: body.is_game_state_public,
					game_state_delay: body.game_state_delay,
                    estimated_tick_time_remaining: parseInt(body.estimated_tick_time_remaining),
                });
            })
            .catch((error) => {
                console.log(error);
            });
    }

    loadScores() {
        //if close to a tick then start updating, otherwise hold values
        const ABOVE_VAL = this.state.tick_time_seconds - 20;
        const BELOW_VAL = 20;

        if (this.state.estimated_tick_time_remaining < BELOW_VAL ||
            this.state.estimated_tick_time_remaining > ABOVE_VAL || this.state.scores.length === 0) {

            fetch('/api/v1/scores', {method: 'GET',})
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.setState({
                        scores: body,
                    });

                })
                .catch((error) => {
                    console.log(error);
                });
        }
    }

    loadServices() {
        fetch('/api/v1/services', {method: 'GET',})
            .then(response => response.json().then(body => ({body, status: response.status})))
            .then(({body, status}) => {
                if (status !== 200) {
                    console.log(status);
                    console.log(body.message);
                    return;
                }
                this.setState({
                    services: body.services,
                });
            })
            .catch((error) => {
                console.log(error);
            });

    }

    loadTeams() {
        fetch('/api/v1/teams', {method: 'GET',})
            .then(response => response.json().then(body => ({body, status: response.status})))
            .then(({body, status}) => {
                if (status !== 200) {
                    console.log(status);
                    console.log(body.message);
                    return;
                }

                this.setState({
                    teams: body.teams,
                });
            })
            .catch((error) => {
                console.log(error);
            });

    }

    changeGameState(event) {
        const newGameState = event.target.value;
        if (newGameState !== "") {
            if (window.confirm("Are you sure you want to set the game state to " + newGameState + "?")) {
                fetch('/api/v1/game/state', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
                    },
                    body: "state=" + encodeURIComponent(newGameState)
                })
                    .then(response => response.json().then(body => ({body, status: response.status})))
                    .then(({body, status}) => {
                        if (status !== 200) {
                            console.log(status);
                            console.log(body.message);
                            return;
                        }
                        this.updateFrequently();
                    })
                    .catch((error) => {
                        console.log(error);
                    });

            }
        }
    }

    changeTickTime(event) {
        var newTickTime = parseInt(event.target[0].value);
        if (window.confirm("Are you sure you want to set the tick time to " + newTickTime + " seconds?")) {
            fetch('/api/v1/tick/time', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8'
                },
                body: "tick_time_seconds=" + encodeURIComponent(newTickTime)
            })
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.updateFrequently();
                })
                .catch((error) => {
                    console.log(error);
                });
        }
        event.preventDefault();
    }

	changeGameStateDelay(event) {
		var newGameStateDelay = parseInt(event.target[0].value);
        if (window.confirm("Are you sure you want to set Game State Delay to " + newGameStateDelay + " ticks?")) {
            fetch('/api/v1/game/game_state_delay/' + newGameStateDelay, {method: "POST",})
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.updateFrequently();
                })
                .catch((error) => {
                    console.log(error);
                });
        }
        event.preventDefault();
	}

	updateIsGameStatePublic(event) {
		const newValue = event.target.value;
        var displayText = "";
        if (isNaN(newValue)) {
            displayText = newValue;
        } else {
            if (newValue === "1") {
                displayText = "Yes";
            } else {
                displayText = "No";
            }
        }
        if (window.confirm("Are you sure you want to set Is Game State Public to " + displayText + "?")) {
            fetch('/api/v1/game/is_game_state_public/' + newValue, {method: "POST",})
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.updateFrequently();
                })
                .catch((error) => {
                    console.log(error);
                });
        }
        event.preventDefault();
	}

    updateService(event) {
        const toChange = event.target.id;
        const newValue = event.target.value;

        const serviceId = event.target.getAttribute('serviceid');
        const serviceName = event.target.getAttribute('servicename');

        var displayText = "";
        if (isNaN(newValue)) {
            displayText = newValue;
        } else {
            if (newValue === "1") {
                displayText = "Yes";
            } else {
                displayText = "No";
            }
        }

        if (window.confirm("Are you sure you want to set " + toChange + " to " + displayText + " on service " + serviceName + "?")) {
            fetch('/api/v1/service/' + serviceId + '/' + toChange + '/' + newValue, {method: "POST",})
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.updateFrequently();
                })
                .catch((error) => {
                    console.log(error);
                });
        }
        event.preventDefault();
    }

    startGame(event) {
        if (window.confirm("Are you sure you want to start the game?")) {
            fetch('/api/v1/game/start', {
                method: 'POST',
            })
                .then(response => response.json().then(body => ({body, status: response.status})))
                .then(({body, status}) => {
                    if (status !== 200) {
                        console.log(status);
                        console.log(body.message);
                        return;
                    }
                    this.updateFrequently();
                })
                .catch((error) => {
                    console.log(error);
                });
        }
        event.preventDefault();
    }

    renderTeamScores() {
        let score_data = [];
        const TEAMS_PER_ROW = 4;
        let merged_rows = [];
        const titles = ["Name", "Atk", "Def", "KoH", "Total", " "];
        let header_titles = [];

        if (this.state.scores.length === 0) {
            return (<div>No Scores Yet</div>)
        }

        this.smoosh_scores(score_data);

        // sort into ascending order by TOTAL
        score_data.sort((a, b) => b.TOTAL - a.TOTAL);

        App.merge_rows(score_data, TEAMS_PER_ROW, merged_rows);

        for (let x = 0; x < TEAMS_PER_ROW; x++) {
            for (let ti = 0; ti < titles.length; ti++) {
                header_titles.push(titles[ti]);
            }
        }

        const header_row = <tr className="row_header">
            {header_titles.map((title) => {
                return (
                    <td>{title}</td>
                );
            })}
        </tr>;
        const col_row = <colgroup>
            <col span={titles.length} className="white_col"/>
            <col span={titles.length} className="grey_col"/>
            <col span={titles.length} className="white_col"/>
            <col span={titles.length} className="grey_col"/>
        </colgroup>;

        const table_data = merged_rows.map((row) => {
            return (
                <tr>
                    {row.map((ele) => {
                        return (
                            <React.Fragment>
                                <td>{ele.name}&nbsp;</td>
                                <td>{ele.ATTACK}</td>
                                <td>{ele.DEFENSE}</td>
                                <td>{ele.KING_OF_THE_HILL}</td>
                                <td>{ele.TOTAL}</td>
                                <td>&nbsp;</td>
                            </React.Fragment>
                        );
                    })}
                </tr>
            );
        });

        return (<table>{col_row} {header_row} {table_data}</table>);

    }

    static merge_rows(score_data, TEAMS_PER_ROW, merged_rows) {
        for (let team_ptr = 0; team_ptr < score_data.length; team_ptr += 4) {
            let row = [];
            for (let offset = 0; offset < TEAMS_PER_ROW; offset++) {
                if (team_ptr + offset < score_data.length) {
                    row.push(score_data[team_ptr + offset]);
                } else {
                    row.push({"id": 1, "name": "", "ATTACK": "", "DEFENSE": "", "KING_OF_THE_HILL": "", "TOTAL": ""});
                }
            }
            merged_rows.push(row);
        }

    }

    smoosh_scores(score_data) {
        // smoosh all ticks into a single dictionary for each team
        for (let tick = 0; tick < this.state.scores.length; tick++) {
            let tick_data = this.state.scores[tick].teams;
            for (let key in tick_data) {
                if (tick_data.hasOwnProperty(key)) {
                    let team_id = tick_data[key]["id"];
                    let team_ptr = team_id - 1;

                    if (team_ptr >= score_data.length) {
                        let new_data = {
                            "id": team_id, "name": this.state.teams[team_ptr].name,
                            "ATTACK": tick_data[team_id].ATTACK,
                            "DEFENSE": tick_data[team_id].DEFENSE,
                            "KING_OF_THE_HILL": tick_data[team_id].KING_OF_THE_HILL,
                            "TOTAL": tick_data[team_id].ATTACK + tick_data[team_id].DEFENSE + tick_data[team_id].KING_OF_THE_HILL
                        };
                        score_data.push(new_data)
                    } else {
                        score_data[team_ptr].ATTACK += tick_data[team_id].ATTACK;
                        score_data[team_ptr].DEFENSE += tick_data[team_id].DEFENSE;
                        score_data[team_ptr].KING_OF_THE_HILL += tick_data[team_id].KING_OF_THE_HILL;
                        score_data[team_ptr].TOTAL += tick_data[team_id].ATTACK + tick_data[team_id].DEFENSE + tick_data[team_id].KING_OF_THE_HILL;
                    }

                }

            }
        }

    }


    outputTeamScores(event) {
        if (window.confirm("Generate formatted JSON file of scores?")) {
            fetch('/api/v1/ctftime', {method: 'GET',})
            .then(response => response.json().then(body => ({body, status: response.status})))
            .then(({body, status}) => {
                if (status !== 200) {
                    console.log(status);
                    console.log(body.message);
                    return;
                }

            })
            .catch((error) => {
                console.log(error);
            });

        }
        event.preventDefault();
    }


    render() {

        const team_info = this.state.teams.map((team) => {
            return (
                <div className="team_info_item">{team.id}) {team.name} </div>
            );
        });

        const team_scores = this.renderTeamScores();


        const services_info = this.state.services.map((service) => {

		
	    const sla_scripts_info = service.sla_scripts.map((sla_script_info) => 
		    <li>{sla_script_info}</li>
	    );

		
	    const local_interaction_scripts_info = service.local_interaction_scripts.map((local_interaction_script_info) => 
		    <li>{local_interaction_script_info}</li>
	    );

            return (
                <div>
                    <h3>{service.name}</h3>
                    <ul>
                        <li>ID: {service.id}</li>
                        <li>Type: {service.type}</li>
                        <li>Isolation: {service.isolation}</li>
                        <li>Repo: {service.repo_url}</li>
                        <li>Port: {service.port}</li>
                        <li>Central Server: {service.central_server}</li>
                        <li>Check Timeout: {service.check_timeout}</li>
                        <li>Memory Limit: {service.limit_memory}</li>
                        <li>Memory Request: {service.request_memory}</li>
                        <li>Service Docker: {service.service_docker}</li>
                        <li>Interaction Docker: {service.interaction_docker}</li>
                        <li>Flag Location: {service.flag_location}</li>
                        <li>Score Location: {service.score_location}</li>
                        <li>Description: {service.description}</li>
                        <li>Is Visible?: {service.is_visible ? "Yes" : "No"}</li>
                        <form>
                            <select onChange={this.updateService.bind(this)} id="is_visible" serviceid={service.id}
                                    servicename={service.name}>
                                <option value="">Set Service to Visible?</option>
                                <option value="1">Yes</option>
                                <option value="0">No</option>
                            </select>
                        </form>

                        <li>Is Active?: {service.is_active ? "Yes" : "No"}</li>
                        <form>
                            <select onChange={this.updateService.bind(this)} id="is_active" serviceId={service.id}
                                    serviceName={service.name}>
                                <option value="">Set Service to Active?</option>
                                <option value="1">Yes</option>
                                <option value="0">No</option>
                            </select>
                        </form>
                        <li>Pcaps Released?: {service.release_pcaps ? "Yes" : "No"}</li>
                        <form>
                            <select onChange={this.updateService.bind(this)} id="release_pcaps" serviceId={service.id}
                                    serviceName={service.name}>
                                <option value="">Release Pcaps?</option>
                                <option value="1">Yes</option>
                                <option value="0">No</option>
                            </select>
                        </form>

                        <li>Service Status Indicator: {service.service_indicator}</li>
                        <form>
                            <select onChange={this.updateService.bind(this)} id="service_indicator"
                                    serviceId={service.id} serviceName={service.name}>
                                <option value="">Change Service Status Indicator?</option>
                                <option value="GOOD">Good</option>
                                <option value="OK">OK</option>
                                <option value="LOW">Low</option>
                                <option value="BAD">Bad</option>
                            </select>
                        </form>

			<li>Local Interaction Scripts: {service.local_interaction_scripts.length}</li>
			<ul>{local_interaction_scripts_info}</ul>

			<li>SLA Scripts: {service.sla_scripts.length}</li>
			<ul>{sla_scripts_info}</ul>

                    </ul>
                </div>


            );
        });

        const changeState = this.state.state === "INIT" ? (
                <form onSubmit={this.startGame.bind(this)}><input type="submit" value="Start Game"/></form>) :
            (
                <form>
                    <select onChange={this.changeGameState.bind(this)} id="changeState">
                        <option value="">Change the State</option>
                        <option value="RUNNING">Running</option>
                        <option value="PAUSED">Paused</option>
                        <option value="STOPPED">Stopped</option>
                    </select>
                </form>
            );

        return (
            <div>
                <h1>DC 28 Admin Interface</h1>
                <div className="team_list">{team_info}</div>
                <h2>Game State</h2>
                <p>
                    <p>State: {this.state.state}</p>
                    {changeState}
                    <p>Tick: {this.state.tick}</p>
                    <p>Tick Time (seconds): {this.state.tick_time_seconds}</p>
                    <p>New Tick Time (seconds): <form onSubmit={this.changeTickTime.bind(this)}><input
                        type="text"/><input type="submit" value="Change Tick Time"/>
                    </form>
                    </p>
                    <p>Est. Tick Time Remaining: {this.state.estimated_tick_time_remaining}</p>
				<p>Is Game State Public?: {this.state.is_game_state_public ? "Yes" : "No"}</p>
				<form>
				  <select onChange={this.updateIsGameStatePublic.bind(this)} id='updateIsGameStatePublic'>
				    <option value="">Make Game State Public?</option>
				    <option value="1">Yes</option>
				    <option value="0">No</option>
				  </select>
				</form>
				<p># of ticks that game state is delayed by: {this.state.game_state_delay}</p>
                <p>New Game State Delay (ticks): <form onSubmit={this.changeGameStateDelay.bind(this)}><input type="text"/><input type="submit" value="Change Game State Delay"/>
                </form>
                </p>

                </p>
                <p>
                    <h2>Scores</h2>
                    <p>{team_scores}</p>
                    <form onSubmit={this.outputTeamScores.bind(this)}><input type="submit" value="Output TeamScores"/>
                    </form>
                </p>
                <p>
                    <h2>Services</h2>
                    {services_info}
                </p>

            </div>
        );
    }
}

export default App;
