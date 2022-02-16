import React from 'react';
import ReactDOM from 'react-dom';
import './index.css';
import App from './App';
import Ticket from './Ticket';
import registerServiceWorker from './registerServiceWorker';
import { Route, Link, HashRouter as Router, Switch, Redirect } from 'react-router-dom'

const routing = (
  <Router>
      <div>
      <ul>
        <li>
          <Link to="/admin">Game Admin</Link>
        </li>
        <li>
          <Link to="/ticket">Ticket Admin</Link>
        </li>
		<li>
		  <a href="/rq/">Patch Admin</a>
		</li>
      </ul>
          <Switch>
              <Route path="/admin" component={App} />
              <Route path="/ticket" component={Ticket} />
              <Redirect from="/" to="/admin" />
            </Switch>


    </div>
  </Router>
)

ReactDOM.render(routing, document.getElementById('root'));

registerServiceWorker();
