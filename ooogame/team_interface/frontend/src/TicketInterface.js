import React, { PureComponent } from 'react';
import logo from './ooo-logo-175.png';
import Avatar from 'react-avatar';

var dateformat = require('dateformat');

class TicketInterface extends PureComponent {
  constructor(props) {
    super(props);
    this.state = {
      tickets: [],
      ticket_result: '',
      msg_result: {},
      allow_vis: []
    };
  }

  componentDidMount() {
    this.loadTicketData();
    this.intervalId = setInterval(() => {
      this.loadTicketData();
    }, 60000);
  }

  componentWillUnmount() {
    clearInterval(this.intervalId);
  }

  loadTicketData() {
    fetch('/api/tickets', {
      method: 'GET'
    })
      .then(response =>
        response.json().then(body => ({ body, status: response.status }))
      )
      .then(({ body, status }) => {
        if (status !== 200) {
          console.log(status);
          console.log(body.message);
          return;
        }
        this.setState({
          tickets: body.tickets
        });
      })
      .catch(error => {
        console.log(error);
      });
  }

  submitFlag(event) {
    event.preventDefault();
  }

  handleChange(event) {
    this.setState({ flag: event.target.value });
  }

  determineVis(tid, tstat) {
    if (this.state.allow_vis.includes(tid.toString())) {
      if (tstat === 'OPEN') {
        return false;
      } else {
        return true;
      }
    }
    return tstat === 'OPEN';
  }

  handleRowClick(event) {
    const ticket_id = event.target.getAttribute('ticket_id');
    let allow_vis = this.state.allow_vis;
    var index = allow_vis.indexOf(ticket_id);
    if (index > -1) {
      allow_vis.splice(index, 1);
      event.target.innerHTML = '+';
    } else {
      event.target.innerHTML = '-';
      allow_vis.push(ticket_id);
    }
    this.setState({ allow_vis: allow_vis });
    this.forceUpdate();
  }

  handleMsgTextChange(event) {
    this.setState({ response_msg: event.target.value });
  }

  clearMessage(ticket_id) {
    let msg_result = this.state.msg_result;
    msg_result[ticket_id] = '';

    this.setState({
      msg_result: msg_result
    });
  }

  enableReply(reply_text_id, reply_btn_id, doclear) {
    document.getElementById(reply_text_id).removeAttribute('disabled');
    document.getElementById(reply_btn_id).innerHTML = 'Reply';
    document.getElementById(reply_btn_id).removeAttribute('disabled');
    if (doclear) {
      document.getElementById(reply_text_id).value = '';
    }
  }

  handleMsgReplyClick(event) {
    const ticket_id = event.target.getAttribute('ticket_id');
    const reply_text_id = 'reply_text_' + ticket_id;
    const reply_btn_id = 'reply_btn_' + ticket_id;

    document.getElementById(reply_text_id).setAttribute('disabled', 'disabled');
    document.getElementById(reply_btn_id).innerHTML = 'Saving...';
    document.getElementById(reply_btn_id).setAttribute('disabled', 'disabled');

    const formData = new FormData();
    formData.append('message_text', this.state.response_msg);

    let url = '/api/ticket/' + ticket_id + '/message';
    let msg_list = this.state.msg_result;
    fetch(url, { method: 'POST', body: formData })
      .then(response => {
        setTimeout(this.clearMessage.bind(this), 5000, ticket_id);
        let status = response.status;
        if (status !== 200) {
          setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, true);
          msg_list[ticket_id] =
            'Error: Received response code ' + status.toString();
          this.setState({
            msg_result: msg_list
          });
          return;
        }
        response.json().then(body => {
          setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, true);
          msg_list[ticket_id] = body.message;
          this.setState({ msg_result: msg_list, is_disabled: false });
          this.loadTicketData();
        });
      })
      .catch(error => {
        setTimeout(this.clearMessage.bind(this), 5000, ticket_id);
        setTimeout(this.enableReply, 1500, reply_text_id, reply_btn_id, false);
        msg_list[ticket_id] = 'Error: ' + error.toString();
        this.setState({
          msg_result: msg_list
        });
      });
  }

  enableTicketCreate(doclear) {
    document.getElementById('new-ticket-submit').removeAttribute('disabled');
    document.getElementById('new-ticket-submit').innerHTML = 'Create Ticket';
    document.getElementById('new-ticket-subject').removeAttribute('disabled');
    document
      .getElementById('new-ticket-description')
      .removeAttribute('disabled');
    if (doclear) {
      document.getElementById('new-ticket-subject').value = '';
      document.getElementById('new-ticket-description').value = '';
    }
  }

  handleNewTicketClick(event) {
    const subject = document.getElementById('new-ticket-subject').value;
    const description = document.getElementById('new-ticket-description').value;

    document
      .getElementById('new-ticket-submit')
      .setAttribute('disabled', 'disabled');
    document.getElementById('new-ticket-submit').innerHTML = 'Creating...';
    document
      .getElementById('new-ticket-subject')
      .setAttribute('disabled', 'disabled');
    document
      .getElementById('new-ticket-description')
      .setAttribute('disabled', 'disabled');

    const formData = new FormData();
    formData.append('subject', subject);
    formData.append('description', description);

    // need subject, description only
    let url = '/api/ticket';
    fetch(url, { method: 'POST', body: formData })
      .then(response => {
        let status = response.status;
        if (status !== 200) {
          setTimeout(this.enableTicketCreate, 3000, false);
          this.setState({
            ticket_result: 'Error: Received response code ' + status.toString()
          });
          return;
        }
        response.json().then(body => {
          setTimeout(this.enableTicketCreate, 3000, true);
          this.loadTicketData();
          this.setState({ ticket_result: body.message });
        });
      })
      .catch(error => {
        setTimeout(this.enableTicketCreate, 3000, false);
        this.setState({
          ticket_result: 'Error: ' + error.toString()
        });
      });
  }

  renderTickets(desired_status) {
    const ticket_rendering = this.state.tickets.map(ticket => {
      if (ticket.status !== desired_status) {
        return '';
      }
      var create_dt = new Date(Date.parse(ticket.created_on));
      var out_date = dateformat(create_dt, 'ddd @ h:MM TT');

      let messages_rend = ticket.messages.map(msg => {
        let username = ticket.team_name;
        let avatar = (
          <div className="avatar">
            <Avatar
              round="true"
              size="60px"
              value={'T' + ticket.team_id}
              maxInitials={3}
            />
          </div>
        );
        if (!msg.is_team_message) {
          avatar = (
            <div className="avatar">
              <img alt="ooo logo" src={logo} width={'60'} />
            </div>
          );
          username = 'OOO';
        }

        var create_dt = new Date(Date.parse(msg.created_on));
        var out_date = dateformat(create_dt, 'ddd @ h:MM TT');
        return (
          <table className={'ticket'} key={`ticket(${ticket.id},${msg.id})`}>
            <tbody>
              <tr>
                <td rowSpan="2">{avatar}</td>
                <td valign="top" height={'10%'}>
                  <div className="replier">{username}</div>
                </td>
                <td>
                  <div className={'reply_time'}>{out_date}</div>
                </td>
              </tr>
              <tr>
                <td colSpan="2" valign={'top'}>
                  <div className={'reply_text'}>{msg.message_text}</div>
                </td>
              </tr>
            </tbody>
          </table>
        );
      });
      const no_messages_rend = <div className={'m-1'}>No Messages Yet</div>;

      let do_display = '';
      let title_block = 'open_title_block';
      let expander_char = '-';
      let do_closed = '';
      if (!this.determineVis(ticket.id, ticket.status)) {
        do_display = ' no-display';
        title_block = 'closed_title_block';
        expander_char = '+';
        do_closed = 'ticket_closed';
      }

      messages_rend =
        messages_rend.length === 0 ? no_messages_rend : messages_rend;
      return (
        <div className={'t-con ' + do_closed} key={ticket.id}>
          <div className={'title_block ' + title_block + ' ' + do_closed}>
            <div className={'w100 flex'}>
              <div className={'subject item'}>{ticket.subject}</div>
              <div className={'ticket-status item '}>{ticket.status}</div>
              <div className={'tdate item'}>{out_date}</div>
              <div className={'header_team_name item'}>
                <div className={'in-block'}>{ticket.team_name}</div>
                <div className={'ml-1 in-block'}>
                  <button
                    className={'plus'}
                    id={'expander_' + ticket.id}
                    ticket_id={ticket.id}
                    onClick={this.handleRowClick.bind(this)}
                  >
                    {expander_char}
                  </button>
                </div>
              </div>
            </div>
            <div className={'pl-1-5' + do_display}>{ticket.description}</div>
          </div>
          <div className={'message_block' + do_display}>
            {messages_rend}
            <div className={'message_response flex'}>
              <div className={'item w90'}>
                <textarea
                  className={'ticket_input'}
                  id={'reply_text_' + ticket.id}
                  placeholder={'Enter reply here...'}
                  onChange={this.handleMsgTextChange.bind(this)}
                />
              </div>
              <div className={'item'}>
                <button
                  className={'post_response'}
                  id={'reply_btn_' + ticket.id}
                  ticket_id={ticket.id}
                  onClick={this.handleMsgReplyClick.bind(this)}
                >
                  Reply
                </button>
              </div>
            </div>
            <span>{this.state.msg_result[ticket.id]}</span>
          </div>
        </div>
      );
    });
    return ticket_rendering;
  }

  render() {
    const ticket_list = this.renderTickets('OPEN');
    const closed_tickets = this.renderTickets('CLOSED');

    return (
      <section className="mt-6">
        <div className="row justify-content-center">
          <div className="col-md-7 heading-section text-center ">
            <h2 className="mb-4">Tickets </h2>
          </div>
        </div>
        <div className={'container mb-4'}>{ticket_list}</div>
        <div className="container mb-4">
          <div className="row">
            <div className="ftco-search">
              <div className="col-md-12">
                <div className="tab-content p-2">
                  <form
                    onSubmit={this.submitFlag.bind(this)}
                    className="search-job"
                  >
                    <span>{this.state.ticket_result}</span>
                    <fieldset disabled={this.state.isDisabled}>
                      <div className="row no-gutters">
                        <div className={'margin-center flex'}>
                          <div className="item m-1">
                            <input
                              type="text"
                              id={'new-ticket-subject'}
                              className="form-control"
                              placeholder="Enter subject for ticket"
                              value={this.state.flag}
                            />
                          </div>
                          <div className="item">
                            <button
                              type="submit"
                              id={'new-ticket-submit'}
                              className="form-control btn btn-secondary"
                              onClick={this.handleNewTicketClick.bind(this)}
                            >
                              Create Ticket
                            </button>
                          </div>
                        </div>
                      </div>
                      <div className="row no-gutters">
                        <div className={'margin-center flex desc_container'}>
                          <textarea
                            className={'ticket_input form-control'}
                            id={'new-ticket-description'}
                            placeholder={'Enter a description of the problem'}
                          />
                        </div>
                      </div>
                    </fieldset>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="row justify-content-center">
          <div className="col-md-7 heading-section text-center ">
            <h2 className="mb-4">
              {closed_tickets.length > 0 ? 'Closed Tickets' : ''}{' '}
            </h2>
          </div>
        </div>
        <div className={'container mb-4'}>{closed_tickets}</div>
      </section>
    );
  }
}

export default TicketInterface;
