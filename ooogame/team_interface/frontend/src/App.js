import React, { Component } from 'react';
import FlagSubmission from './FlagSubmission';
import TicketInterface from './TicketInterface';
import Upload from './Upload';
import showdown from 'showdown';
import './App.css';

//import { dateformat } from "dateformat";

class App extends Component {
  constructor(props) {
    super(props);
    this.state = {
      team_id: -1,
      team_name: '',
      pcaps: [],
      pub_key: null,
      sec_key: null,
      service_names_by_id: {},
      services: [],
      announcements: [],
      patches: []
    };
  }

  componentDidMount() {
    document.title = 'Team interface - DEF CON CTF';
    this.loadTeamData();
    this.loadPcapData();
    this.loadPatchData();
    this.loadServiceData();
    //this.loadAnnouncements();
    this.loadPatches();
    const intervalId = setInterval(() => {
      this.loadPcapData();
      this.loadServiceData();
      //this.loadAnnouncements();
      this.loadPatches();
      this.loadServiceData(this.state.team_id);
    }, 60000);
    this.setState({ intervalId: intervalId });
  }

  componentWillUnmount() {
    clearInterval(this.state.intervalId);
  }

  loadPcapData() {
    fetch('/api/pcap_info', { method: 'GET' })
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
          pcaps: body
        });
      })
      .catch(error => {
        console.log(error);
      });
  }

  loadPatches() {
    fetch('/api/patches_info', { method: 'GET' })
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
          patches: body
        });
      })
      .catch(error => {
        console.log(error);
      });
  }

  loadPatchData = () => {
    fetch('/api/patches_info', { method: 'GET' })
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
          pub_key: body.pub_key,
          sec_key: body.sec_key
        });
      })
      .catch(error => {
        console.log(error);
      });
  };

  loadTeamData() {
    fetch('/api/team_info', {
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
          team_id: body.id,
          team_name: body.name
        });
      })
      .catch(error => {
        console.log(error);
      });
  }

  loadServiceData() {
    fetch('/api/services_info', {
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
        const service_names_by_id = {};
        for (var service of body.services) {
          service_names_by_id[service.id] = service.name;
        }
        this.setState({
          service_names_by_id,
          services: body.services
        });
      })
      .catch(error => {
        console.log(error);
      });
  }

  renderServices(serviceTitle) {
    const services_info =
      this.state.services.length > 0 ? (
        this.state.services.map(service => {
          let type_badge = '';
          let inac = service.is_active ? '' : 'inactive ';
          if (service.type.toUpperCase() === 'NORMAL') {
            let text = inac.length > 0 ? 'text-' + inac + ' ' : 'text-dark';
            let bg = inac.length > 0 ? ' bg-' + inac + ' ' : ' bg-normal ';
            type_badge = (
              <span className={bg + text + ' badge px-3 mr-2'}>
                Attack/Defense
              </span>
            );
          } else {
            let text = inac.length > 0 ? ' text-' + inac + ' ' : ' text-dark ';
            let bg = inac.length > 0 ? ' bg-' + inac + ' ' : ' bg-koh ';
            type_badge = (
              <span className={bg + text + ' badge px-3 mr-2'}>
                King of the Hill
              </span>
            );
          }
          let status_badge = (
            <span
              className={
                'bg-' +
                service.service_indicator.toLowerCase() +
                ' text-white badge py-2 px-3' +
                inac
              }
            >
              {service.service_indicator}
            </span>
          );

          let service_status = service.is_active
            ? 'service-active'
            : 'service-inactive';
          let pcap_status = service.are_pcaps_released
            ? 'pcaps-yes'
            : 'pcaps-no';
          let bar_color = service.is_active
            ? service.type.toLowerCase()
            : 'service-inactive';
          let text_inactive = '';
          if (inac.length > 0) {
            text_inactive = ' text-inactive ';
            status_badge = '';
            pcap_status = text_inactive + ' border-inactive ';
          }

          const converter = new showdown.Converter({
            literalMidWordUnderscores: true,
            simplifiedAutoLink: true
          });
          const output_desc = converter.makeHtml(service.description);

          return (
            <li className={'li-' + bar_color} key={service.id}>
              <div className={'d-block d-lg-flex' + text_inactive}>
                <div className="two-thirds">
                  <div className="d-inline-block">
                    <div className={'d-inline-block pr-3' + text_inactive}>
                      {service.name}
                    </div>
                    <div className={'d-inline-block pr-3' + text_inactive}>
                      @ {service.team_ip}:{service.port}
                    </div>
                    <div className="d-inline-block">{type_badge}</div>
                  </div>
                </div>
                <div className="one-forth ml-auto d-flex align-items-center">
                  {status_badge}
                </div>
              </div>
              <div>
                <div className="d-inline-block">
                  <div className="d-inline-block pr-5">
                    <span className={'service-deet ' + service_status}>
                      {service.is_active
                        ? 'Service Active'
                        : 'Service Inactive'}
                    </span>
                  </div>
                  <div className="d-inline-block pr-5">
                    {service.type === 'NORMAL' ? (
                      <span className={'service-deet ' + pcap_status}>
                        {service.are_pcaps_released
                          ? 'PCAPs Released'
                          : 'PCAPS Not Released'}
                      </span>
                    ) : (
                      ''
                    )}
                  </div>
                </div>
                <div
                  className={text_inactive}
                  dangerouslySetInnerHTML={{ __html: output_desc }}
                />

                {service.is_active && service.type === 'NORMAL' ? (
                  <Upload
                    callback={this.loadPatchData}
                    serviceId={service.id}
                    serviceName={service.name}
                  />
                ) : (
                  ''
                )}
              </div>
            </li>
          );
        })
      ) : (
        <b>No services released</b>
      );

    return (
      <React.Fragment>
        <div className="row justify-content-center pb-3">
          <div className="col-md-7 heading-section text-center">
            <h2 className="mb-4">{serviceTitle}</h2>
          </div>
        </div>
        <div className="row">
          <div className="col-md-12">
            <ul className="category">{services_info}</ul>
          </div>
        </div>
      </React.Fragment>
    );
  }

  render() {
    const header = (
      <section>
        <div className="container">
          <div className="row">
            <div className="col-md-6">
              Welcome, {this.state.team_name} (#{this.state.team_id})
            </div>
            <div className="col-md-6 text-right">
              <a href="/game_state/game_state.json">
                Game state (delayed from the scoreboard)
              </a>
            </div>
          </div>
        </div>
      </section>
    );

    let pcap_list = <b>No released Pcaps</b>;

    if (this.state.pcaps.length > 0) {
      let pcaps = this.state.pcaps.slice(-10);
      pcaps.reverse();

      pcap_list = pcaps.map(pcap => {
        const service_name =
          this.state.service_names_by_id[pcap.service_id] || pcap.service_id;
        return (
          <li key={pcap.pcap_location}>
            <a href={pcap.pcap_location}>
              Service {service_name} pcap {pcap.created_on}
            </a>
          </li>
        );
      });
    }

    const patches_info =
      this.state.patches.length > 0 ? (
        this.state.patches.map(patch => {
          const public_info = patch.results[0].public_metadata ? (
            <span>Patch information: {patch.results[0].public_metadata}</span>
          ) : (
            <span></span>
          );
          const service_name =
            this.state.service_names_by_id[patch.service_id] ||
            patch.service_id;
          return (
            <li key={patch.id}>
              Patch #{patch.id} for service {service_name} uploaded hash{' '}
              {patch.uploaded_hash} status {patch.results[0].status}.{' '}
              {public_info} <br />
            </li>
          );
        })
      ) : (
        <b>No patches.</b>
      );

    return (
      <div className="container" id="thebigdiv">
        {header}
        <FlagSubmission />
        <section id="topsection">
          <div className="container">{this.renderServices('Services')}</div>
        </section>
        <section>
          <div className="row justify-content-center pb-3">
            <div className="col-md-7 heading-section text-center">
              <h2 className="mb-4">Recent PCAPs</h2>
              <div>
                <a href="/api/pcap_info">See all</a>
              </div>
            </div>
          </div>
          <div className="container row">
            <div className="col-md-12">
              <ul className="category">{pcap_list}</ul>
            </div>
          </div>
        </section>
        <section>
          <div className="row justify-content-center pb-3">
            <div className="col-md-7 heading-section text-center">
              <h2 className="mb-4">Your Submitted Patches </h2>
            </div>
          </div>
          <div className="container row">
            <div className="col-md-12">
              <ul className="category">{patches_info}</ul>
            </div>
          </div>
        </section>
        <TicketInterface />
      </div>
    );
  }
}

export default App;
