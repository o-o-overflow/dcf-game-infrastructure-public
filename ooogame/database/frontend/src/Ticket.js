import './App.css';
import React from 'react'
import logo from './ooo-logo-175.png';
import Avatar from 'react-avatar';

var dateformat = require("dateformat");

class Ticket extends React.Component {

    constructor(props) {
        super(props);
        this.state = {
            state: "",
            tickets: [],
            intervalId: -1,
            current_ticket_id: -1,
            result: "",
            is_disabled: false,
            allow_vis: [],
        };
    }

    componentDidMount() {
        document.title = "Tickets DC Finals";
        this.updateAtStart();
        const intervalId = setInterval(() => this.updateFrequently(), 5000);
        this.setState({
            intervalId: intervalId,
        });

    }

    updateAtStart() {
        this.loadTickets();
    }

    updateFrequently() {
        this.loadTickets();
    }

    componentWillUnmount() {
        clearInterval(this.state.intervalId);
    }

    loadTickets() {
        fetch('/api/v1/tickets', {method: 'GET',})
            .then(response => response.json().then(body => ({body, status: response.status})))
            .then(({body, status}) => {
                if (status !== 200) {
                    console.log(status);
                    console.log(body.message);
                    return;
                }
                this.setState({
                    tickets: body.tickets,
                });
            })
            .catch((error) => {
                console.log(error);
            });
    }

    submitFlag(event) {
        event.preventDefault();

    }

    handleChange(event) {
        this.setState({response_msg: event.target.value});
    }

    enableReply(reply_text_id, reply_btn_id, doclear){
        document.getElementById(reply_text_id).removeAttribute("disabled");
        document.getElementById(reply_btn_id).innerHTML = "Reply";
        document.getElementById(reply_btn_id).removeAttribute("disabled");
        if (doclear){
            document.getElementById(reply_text_id).value = "";
        }

    }

    handleClick(event) {


        const ticket_id = event.target.getAttribute('ticket_id');
        const reply_text_id = "reply_text_" + ticket_id;
        const reply_btn_id = "reply_btn_" + ticket_id;

        document.getElementById(reply_text_id).setAttribute("disabled","disabled");
        document.getElementById(reply_btn_id).innerHTML = "Saving...";
        document.getElementById(reply_btn_id).setAttribute("disabled","disabled");


        const formData = new FormData();
        formData.append('message_text', this.state.response_msg);

        let url = "/api/v1/ticket/" + ticket_id + "/message";

        fetch(url, {method: 'POST', body: formData})
            .then(response => {
                let status = response.status;
                if (status !== 200) {
                    setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, false);
                    this.setState({
                        result: 'Error: Received response code ' + status.toString()
                    });
                    return;
                }
                response.json().then(body => {
                    console.log(reply_text_id, reply_btn_id);
                    setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, true);
                    this.setState({result: body.message, is_disabled: false});
                });
            })
            .catch(error => {
                setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, false);

                this.setState({
                    result: 'Error: ' + error.toString()
                });
            });

    }

    handleStatusClick(event) {
        const ticket_id = event.target.getAttribute('ticket_id');
        const current_status = event.target.getAttribute('current_status');
        let new_status = "OPEN";
        if (current_status === "OPEN")
            new_status = "CLOSED";

        const formData = new FormData();
        formData.append('status', new_status);

        let url = "/api/v1/ticket/status/" + ticket_id;

        fetch(url, {method: 'POST', body: formData})
            .then(response => {
                let status = response.status;
                if (status !== 200) {
                    this.setState({
                        is_disabled: false,
                        result: 'Error: Received response code ' + status.toString()
                    });
                    console.log(status);
                    return;
                }
                response.json().then(body => {
                    this.setState({result: body.message});
                });
            })
            .catch(error => {
                this.setState({
                    result: 'Error: ' + error.toString()
                });
            });


    }
    handleRowClick(event){

        const ticket_id = event.target.getAttribute('ticket_id');
        let allow_vis = this.state.allow_vis;
        var index = allow_vis.indexOf(ticket_id);
        if (index > -1) {
            allow_vis.splice(index, 1);
            event.target.innerHTML = "+";
        } else {
            event.target.innerHTML = "-";
            allow_vis.push(ticket_id);
        }
        console.log(allow_vis);
        this.setState({ allow_vis: allow_vis });

        console.log(this.state.allow_vis);

        this.forceUpdate();
    }
    determineVis(tid, tstat){
        console.log("dv", tid, this.state.allow_vis);
        if (this.state.allow_vis.includes(tid.toString())){
            if (tstat === "OPEN"){
                return false;
            } else {
                return true;
            }
        }
        console.log(tstat, tstat === "OPEN");
        return tstat === "OPEN";

    }
    renderTickets(desired_status) {

        const ticket_rendering = this.state.tickets.map((ticket) => {
            if (ticket.status !== desired_status){
                return ""
            }
            var create_dt = new Date(Date.parse(ticket.created_on));
            var out_date = dateformat(create_dt, "ddd @ h:MM TT");

            let messages_rend = ticket.messages.map(msg => {
                let username = ticket.team_name;
                let avatar = (
                    <div className="avatar" >
                        <Avatar round="true" size="60px" value={"T" + ticket.team_id} maxInitials={"3"}/>
                    </div>
                );
                if (!msg.is_team_message) {
                    avatar = (
                        <div className="avatar">
                            <img src={logo} width={"60"}/>
                        </div>
                    );
                    username = "OOO";
                }

                var create_dt = new Date(Date.parse(msg.created_on));
                var out_date = dateformat(create_dt, "ddd @ h:MM TT");
                return (
                    <table>
                        <tbody>
                        <tr>
                            <td rowspan="2">{avatar}</td>
                            <td valign="top" height={"10%"}><div className="replier">{username}</div></td>
                            <td><div className={"reply_time"}>{out_date}</div></td>
                        </tr>
                        <tr>
                            <td colspan="2" valign={"top"}><div className={"reply_text"}>{msg.message_text}</div></td>
                        </tr>
                        </tbody>
                    </table>

                )
            });
            const no_messages_rend = (
                <div className={"m-1"}>
                    No Messages Yet
                </div>
            )

            let do_display = "";
            let title_block = "open_title_block";
            let expander_char = "-";
            if (!this.determineVis(ticket.id, ticket.status)) {
                do_display = " no-display";
                title_block = "closed_title_block";
                expander_char = "+";
            }

            let ticket_action = "Close This Ticket";
            if(ticket.status == "CLOSED") {
                ticket_action = "Re-Open This Ticket";
            }


            messages_rend = messages_rend.length === 0 ? no_messages_rend : messages_rend;
            return (
                <div className={"container"} key={ticket.id} >
                    <div className={title_block}>
                        <div className={"w100 flex"}>
                            <div className={"subject item"}>{ticket.subject}</div>
                            <div className={"status item"}><b>STATUS:</b> {ticket.status}</div>
                            <div className={"status item "+ do_display}>                            
                                <button
                                       onClick={this.handleStatusClick.bind(this)}
                                       ticket_id={ticket.id}
                                       current_status={ticket.status}>
                                    {ticket_action}
                                </button>
                            </div>
                            <div className={"tdate item"}>{out_date}</div>
                            <div className={"header_team_name item"}>
                                <div className={"in-block"}>
                                    {ticket.team_name}
                                </div>
                                <div className={"ml-1 in-block"}>
                                <button className={"plus"} id={"expander_"+ticket.id}
                                   ticket_id={ticket.id}
                                   onClick={this.handleRowClick.bind(this)}>
                                    {expander_char}
                                </button>
                                </div>
                            </div>

                        </div>
                        <div className={"pl-1-5" + do_display}>
                            {ticket.description}

                        </div>
                    </div>
                    <div className={"message_block" + do_display} >
                        {messages_rend}
                        <div className={"message_response flex"}>
                                <div className={"item w90"}>
                                <textarea className={"response_input"} id={"reply_text_"+ticket.id}
                                          placeholder={"Enter reply here..."}
                                          onChange={this.handleChange.bind(this)}/>
                                </div>
                                <div className={"item"}>
                                    <button className={"post_response"} id={"reply_btn_"+ticket.id}
                                           ticket_id={ticket.id}
                                           onClick={this.handleClick.bind(this)}>
                                        Reply
                                    </button>
                                </div>

                        </div>
                    </div>

                </div>
            );
        });
        return ticket_rendering;
    }

    render() {
        return (
            <div>
                <h1>Open Tickets</h1>

                {this.renderTickets("OPEN")}
                <div className={"m-1"}>
                    <br/>
                </div>
                <hr size={"1px"}/>
                <h1>Closed Tickets</h1>
                {this.renderTickets("CLOSED")}
            </div>
        )
    }
}

export default Ticket
