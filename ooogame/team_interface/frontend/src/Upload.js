import React, {Component} from 'react';

const UPLOAD_PATH = '/api/submit_patch/';

class Upload extends Component {
    constructor(props) {
        super(props);
        this.state = {
            file: undefined,
            status: null
        };
    }

    onChange = e => {
        console.log(e);
        console.log(e.target.files[0]);
        this.setState({file: e.target.files[0], status: null});

    };

    onFormSubmit = e => {
        e.preventDefault();
        const formData = new FormData();
        formData.append('file', this.state.file);
        formData.append('service_id', this.props.serviceId);
        this.setState({file: undefined, status: 'uploading...'});
        fetch(UPLOAD_PATH, {
            body: formData,
            method: 'POST'
        }).then(response => {
            response.json().then(body => {
                this.setState({
                    status: 'Patch upload response: ' + body.message
                });
                this.props.callback();
            });
        });
    };

    render() {
        return (
            <div className="container m-tb-3">
                <div className="row">
                    <div className="ftco-search">
                        <div className="col-md-7">
                            <div className="service-patch-upload p-1">
                                <form onSubmit={this.onFormSubmit} className="search-job">
                                    <div className="row no-gutters">
                                        <div className={" margin-center flex"}>
                                            <div className="item m-1">
                                                <input type="file" name="file" id={"file"+this.props.serviceId} onChange={this.onChange}
                                                       className="inputfile"/>
                                                <label htmlFor={"file"+this.props.serviceId} className="btn btn-secondary ">

                                                    <div
                                                        className={this.state.file === undefined ? " " : "fileprompt"}>Choose
                                                        a patch to upload
                                                    </div
                                                    >
                                                    <div
                                                        className={'filename ' +
                                                        (this.state.file === undefined
                                                            ? 'hideme '
                                                            : ' ')
                                                        }>
                                                        File: {' '}
                                                        {this.state.file === undefined
                                                            ? '' : this.state.file.name}
                                                    </div>
                                                </label>
                                            </div>
                                            <div className="item">
                                                <button type="submit" disabled={this.state.file === undefined}
                                                        className="form-control btn btn-secondary upload">
                                                    Upload
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                    <div className="col-md-12 center-right ml-auto status">
                                        {this.state.status === null ? (
                                            ''
                                        ) : (
                                            <p>Status: {this.state.status}</p>
                                        )}</div>

                                </form>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

        );
    }
}

export default Upload;
