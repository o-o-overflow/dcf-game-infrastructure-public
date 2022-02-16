import React, { Component } from 'react';

class FlagSubmission extends Component {
  constructor(props) {
    super(props);
    this.state = {
      flag: '',
      result: '',
      isDisabled: false
    };
  }

  submitFlag(event) {
    let flag = this.state.flag;
    this.setState({ isDisabled: true });
    fetch('/api/submit_flag/' + flag, { method: 'POST' })
      .then(response => {
        let status = response.status;
        this.setState({ isDisabled: false });
        if (status !== 200) {
          this.setState({
            isDisabled: false,
            result: 'Error: Received response code ' + status.toString()
          });
          console.log(status);
          return;
        }
        response.json().then(body => {
          this.setState({ isDisabled: false, result: body.message });
        });
      })
      .catch(error => {
        this.setState({
          isDisabled: false,
          result: 'Error: ' + error.toString()
        });
      });
    event.preventDefault();
  }

  handleChange(event) {
    this.setState({ flag: event.target.value });
  }

  render() {
    return (
      <section>
        <div className="container">
          <div className="row">
            <div className="ftco-search">
              <div className="col-md-12">
                <div className="tab-content p-2">
                  <form
                    onSubmit={this.submitFlag.bind(this)}
                    className="search-job"
                  >
                    <span>{this.state.result}</span>
                    <fieldset disabled={this.state.isDisabled}>
                      <div className="row no-gutters">
                        <div className={' margin-center flex'}>
                          <div className="item m-1">
                            <input
                              type="text"
                              className="form-control "
                              placeholder="Enter Flag"
                              value={this.state.flag}
                              onChange={this.handleChange.bind(this)}
                            />
                          </div>
                          <div className="item">
                            <button
                              type="submit"
                              className="form-control btn btn-secondary"
                            >
                              Submit Flag
                            </button>
                          </div>
                        </div>
                      </div>
                    </fieldset>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    );
  }
}

export default FlagSubmission;
